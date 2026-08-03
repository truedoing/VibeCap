#!/usr/bin/env python3
"""素材搜索服务 v2: HuggingFace语义搜索 + 关键词兜底"""
import json, re, subprocess, pickle, time, threading, os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse, parse_qs
import numpy as np

# ── SQLite 数据库层 ──
from db import VibeCapDB
DB_PATH = Path(__file__).resolve().parent.parent / "vibecap.db"
db = VibeCapDB(str(DB_PATH))

# 注入语义搜索函数到 Agent 系统
# v3: 强制离线模式, 模型已在本地缓存, 避免 HF mirror 超时
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
try:
    from script_agents import set_search_fn
    def _agent_search(query, limit=15):
        """供 Agent 使用的语义搜索"""
        if semantic_emb is None: return []
        q_emb = _encode(query)
        scores = np.dot(semantic_emb, q_emb)
        top = np.argsort(scores)[-limit*2:][::-1]
        results = []
        metas = semantic_metas
        for i in top:
            if scores[i] <= 0.25: continue
            m = metas[i]
            # v3: 优先返回 original_text (ASR原文), fallback text (清洗后)
            display_text = m.get("original_text", m.get("text", ""))
            results.append({
                "start": m.get("start", 0), "end": m.get("end", m.get("start", 0) + 4),
                "description": display_text[:200], "asr": display_text[:200],
                "cleaned_text": m.get("text", "")[:200],  # 清洗后文本(供后续处理)
                "score": round(float(scores[i]) * 100, 1),
            })
        return sorted(results, key=lambda x: -x["score"])[:limit]
    set_search_fn(_agent_search)
    # 同步预热: 确保 pipeline 启动前模型已就绪
    print("[agent] 预热 BGE 模型 (本地缓存, ~8s)...")
    import threading
    warm_ready = threading.Event()
    def _warm():
        try:
            _agent_search("预热", limit=1)
            print("[agent] BGE 模型预热完成 ✓")
            warm_ready.set()
        except Exception as e:
            print(f"[agent] 预热失败: {e}")
            warm_ready.set()
    threading.Thread(target=_warm, daemon=True).start()
    # 等最多 30 秒
    if not warm_ready.wait(timeout=30):
        print("[agent] ⚠️ 预热超时(30s), 搜索可能较慢")
except Exception as e:
    print(f"[agent] search injection failed: {e}")

# ── 后台加工流水线 ──
_process_tasks = {}  # {task_id: {episodes, steps, current}}
_process_lock = threading.Lock()

def _run_pipeline(task_id, episodes, drama_name):
    """后台执行数据加工流水线，实时解析进度"""
    server_dir = Path(__file__).resolve().parent
    python_bin = "/opt/anaconda3/bin/python3"
    all_eps_str = ",".join(str(e) for e in episodes)

    steps = [
        {"id": "analyze",  "label": f"分析 EP{all_eps_str}", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "calibrate","label": "交叉校准", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "clean",    "label": "数据清洗", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "build",    "label": "重建索引", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "migrate",  "label": "导入数据库", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
    ]

    with _process_lock:
        _process_tasks[task_id] = {"episodes": episodes, "steps": steps,
                                     "started_at": time.time()}

    def _update(i, **kw):
        with _process_lock:
            t = _process_tasks.get(task_id)
            if t: t["steps"][i].update(kw)

    def _run_script(step_idx, script_name, args, timeout, progress_parser=None):
        """运行脚本并逐行解析进度"""
        _update(step_idx, status="running", detail="启动中...")
        t0 = time.time()
        log_lines = []

        try:
            p = subprocess.Popen(
                [python_bin, "-u", str(server_dir / script_name)] + args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            # 逐行读取
            total = 0
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    log_lines.append(line)
                    if len(log_lines) > 8:
                        log_lines = log_lines[-8:]
                    elapsed = round(time.time() - t0, 1)
                    detail = line[:80]

                    # 尝试解析进度: [N/M] 或 N/M
                    m = re.search(r'\[?\s*(\d+)\s*/\s*(\d+)\s*\]?', line)
                    if m and progress_parser:
                        current, total = int(m.group(1)), int(m.group(2))
                        pct = min(99, round(current / max(total, 1) * 100))
                        _update(step_idx, progress=pct, detail=detail,
                                elapsed=elapsed, log_lines=list(log_lines))
                    else:
                        _update(step_idx, detail=detail, elapsed=elapsed,
                                log_lines=list(log_lines))

            p.wait(timeout=timeout)
            elapsed = round(time.time() - t0, 1)
            if p.returncode == 0:
                _update(step_idx, status="done", progress=100,
                        elapsed=elapsed, log_lines=list(log_lines))
                return True
            else:
                last_log = "\n".join(log_lines[-3:]) if log_lines else "未知错误"
                _update(step_idx, status="failed", detail=f"退出码 {p.returncode}",
                        elapsed=elapsed, log_lines=list(log_lines))
                return False
        except subprocess.TimeoutExpired:
            p.kill()
            _update(step_idx, status="failed", detail="超时",
                    elapsed=round(time.time() - t0, 1))
            return False
        except Exception as e:
            _update(step_idx, status="failed", detail=str(e)[:80],
                    elapsed=round(time.time() - t0, 1))
            return False

    # Step 1: 分析剧集
    if not _run_script(0, "analyze_episodes.py", ["--ep", all_eps_str, "--asr-model", "small"], 3600, True):
        return

    # Step 2: 交叉校准 ASR↔VLM
    if not _run_script(1, "cross_calibrate.py", ["--ep", all_eps_str], 120, True):
        return

    # Step 3: 数据清洗
    if not _run_script(2, "clean_data.py", ["--ep", all_eps_str], 300, True):
        return

    # Step 4: 重建索引
    if not _run_script(3, "build_index.py", [], 600, True):
        return

    # Step 5: 导入数据库
    _run_script(4, "migrate_db.py", [], 120, True)

# ── 口播采访流水线 ──
def _run_interview_pipeline(task_id, project_name, step="all"):
    """后台执行口播采访数据加工流水线"""
    server_dir = Path(__file__).resolve().parent
    python_bin = "/opt/anaconda3/bin/python3"

    steps = [
        {"id": "classify", "label": "LLM 分类 (content/meta/guide/filler)", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "segment", "label": "LLM 分段 (5-8个主题组)", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "index",   "label": "语义索引 (BGE)", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "report",  "label": "质量评分", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
    ]

    with _process_lock:
        _process_tasks[task_id] = {"episodes": [], "steps": steps, "started_at": time.time()}

    def _update(i, **kw):
        with _process_lock:
            t = _process_tasks.get(task_id)
            if t: t["steps"][i].update(kw)

    def _run(step_idx, script_name, args, timeout, progress_parser=True):
        _update(step_idx, status="running", detail="启动中...")
        t0 = time.time()
        log_lines = []
        try:
            p = subprocess.Popen(
                [python_bin, "-u", str(server_dir / script_name)] + args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    log_lines.append(line)
                    if len(log_lines) > 8: log_lines = log_lines[-8:]
                    elapsed = round(time.time() - t0, 1)
                    detail = line[:80]
                    m = re.search(r'\[?\s*(\d+)\s*/\s*(\d+)\s*\]?', line)
                    if m and progress_parser:
                        current, total = int(m.group(1)), int(m.group(2))
                        pct = min(99, round(current / max(total, 1) * 100))
                        _update(step_idx, progress=pct, detail=detail, elapsed=elapsed, log_lines=list(log_lines))
                    else:
                        _update(step_idx, detail=detail, elapsed=elapsed, log_lines=list(log_lines))
            p.wait(timeout=timeout)
            elapsed = round(time.time() - t0, 1)
            if p.returncode == 0:
                _update(step_idx, status="done", progress=100, elapsed=elapsed, log_lines=list(log_lines))
                return True
            else:
                _update(step_idx, status="failed", detail=f"退出码 {p.returncode}", elapsed=elapsed, log_lines=list(log_lines))
                return False
        except subprocess.TimeoutExpired:
            p.kill()
            _update(step_idx, status="failed", detail="超时", elapsed=round(time.time() - t0, 1))
            return False
        except Exception as e:
            _update(step_idx, status="failed", detail=str(e)[:80], elapsed=round(time.time() - t0, 1))
            return False

    # Step 1: LLM 分类
    if step in ("all", "classify"):
        _run(0, "classify_transcript.py", ["--project", project_name], 3600)

    # Step 2: LLM 分段
    if step in ("all", "segment"):
        _run(1, "segment_transcript.py", ["--project", project_name], 600)

    # Step 3: 语义索引
    if step in ("all", "index"):
        _run(2, "build_interview_index.py", ["--project", project_name], 600)

    # Step 4: 质量评分 (调用 db.compute_quality_report)
    if step in ("all", "report"):
        _update(3, status="running", detail="计算中...")
        t0 = time.time()
        try:
            drama_id = db.get_drama_id(project_name)
            if not drama_id: drama_id = db.ensure_drama(project_name)
            if drama_id:
                report = db.compute_quality_report(drama_id, 1, str(BASE_DIR / project_name))
                _update(3, status="done", progress=100, elapsed=round(time.time() - t0, 1),
                        detail=f"综合: {report.get('overall_score', 0)}分")
        except Exception as e:
            _update(3, status="failed", detail=str(e)[:80])

# 繁→简 转换
try:
    from zhconv import convert as _zh_convert
    def _norm(text):
        """繁体转简体，用于 ASR 文本归一化"""
        return _zh_convert(text, 'zh-cn')
except ImportError:
    def _norm(text):
        return text

# 国内 HuggingFace 镜像（hf-mirror.com）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 加载本地 .env（API Keys）
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                if not os.environ.get(_k.strip()):  # 未设置或为空 → 从.env加载
                    os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

# ── CLI 参数 ──
import argparse as _argparse
_parser = _argparse.ArgumentParser(description="VIBECAP 后端服务")
_parser.add_argument("--project", default=os.environ.get("VIBECAP_PROJECT", ""), help="项目名")
_parser.add_argument("--drama", default=os.environ.get("VIBECAP_DRAMA", ""), help="电视剧名 (兼容旧参数)")
_parser.add_argument("--task", default=os.environ.get("VIBECAP_TASK", "Task7024"), help="任务名")
_parser.add_argument("--port", type=int, default=8765, help="端口")
_args = _parser.parse_args()

BASE_DIR    = Path("/Users/zgl/VIBECAP")
FRONTEND_DIR = BASE_DIR / "vibecap-web" / "dist"

# ── 项目配置加载 ──
_project_name = _args.project or _args.drama or "都挺好"
_project_config = {}
_project_type = "drama"  # drama | interview
PROJECT_DIR = BASE_DIR / _project_name

# 尝试加载项目配置
_cfg_path = BASE_DIR / "projects" / f"{_project_name}.json"
if _cfg_path.exists():
    _project_config = json.load(open(_cfg_path))
    _project_type = _project_config.get("type", "drama")
    print(f"[project] {_project_name} (type={_project_type})")
else:
    print(f"[project] {_project_name} (legacy mode, no project config)")

# 通用路径
SOURCES_DIR = PROJECT_DIR / "sources"
PROXY_DIR   = PROJECT_DIR / "proxies"
PROXY_DIR.mkdir(exist_ok=True)
PROXY_MANIFEST = PROXY_DIR / ".proxies_manifest.json"

# 任务目录: 支持 --task 参数动态切换
def _resolve_task_dir(task_name=None):
    name = task_name or _args.task
    return PROJECT_DIR / "tasks" / name

TASK_DIR    = _resolve_task_dir()
WORK_DIR    = TASK_DIR / "work_dir"
CLIP_DIR    = TASK_DIR / "素材clips"
CLIP_DIR.mkdir(exist_ok=True)
WORK_DIR.mkdir(exist_ok=True)

# ── 源视频索引 ──
SOURCE_VIDEOS = {}
if _project_type == "drama":
    _video_dir = Path(_project_config.get("source_videos", f"/Users/zgl/解说剪辑/{_project_name}原剧"))
    for ep in range(1, _project_config.get("episodes", 46) + 1):
        p = _video_dir / f"{_project_name} {ep:02d}_1080p.mp4"
        if p.exists():
            SOURCE_VIDEOS[f"ep{ep}"] = p
elif _project_type == "interview":
    _video_dir = Path(_project_config.get("source_videos", ""))
    if _video_dir.exists():
        for f in sorted(_video_dir.glob("*.mp4")):
            SOURCE_VIDEOS[f.stem] = f
    print(f"[project] 口播素材: {len(SOURCE_VIDEOS)} 个视频")

class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

# ── 加载数据 (按项目类型) ──
INDEX_FILE  = PROJECT_DIR / "semantic_index.pkl"  # drama only
INDEX_NPY   = PROJECT_DIR / "semantic_embeddings.npy"
INDEX_META  = PROJECT_DIR / "semantic_metas.json"
semantic_emb = None
semantic_metas = None
AVAILABLE_EPS = []
vlm_data = []
asr_data = {}
# interview 模式的 ASR 数据
interview_asr = None

if _project_type == "drama":
    # 语义索引
    if INDEX_NPY.exists() and INDEX_META.exists():
        semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
        semantic_metas = json.load(open(INDEX_META))
        print(f"[search] 语义索引 (mmap): {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")
    elif INDEX_FILE.exists():
        old = pickle.load(open(INDEX_FILE, "rb"))
        semantic_emb = old["embeddings"]
        semantic_metas = old["metas"]
        print(f"[search] 语义索引 (pickle): {semantic_emb.shape[0]} 条")

    # 动态发现可用集数
    AVAILABLE_EPS = sorted(set(
        int(d.name[2:]) for d in SOURCES_DIR.iterdir()
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
        and ((d / "asr_result.json").exists() or (d / "vlm_analysis.json").exists())
    ))
    print(f"[search] 可用集数: {AVAILABLE_EPS}")

    # VLM 数据
    for ep in AVAILABLE_EPS:
        p = SOURCES_DIR / f"ep{ep}" / "vlm_analysis.json"
        if p.exists():
            for s in json.load(open(p)):
                if s is None: continue
                s["_ep"] = ep
                vlm_data.append(s)
    print(f"[search] VLM 数据: {len(vlm_data)} 条")

    # ASR 数据
    for ep in AVAILABLE_EPS:
        p = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
        if p.exists():
            raw = json.load(open(p))
            for a in raw:
                a["text"] = _norm(a["text"])
            asr_data[ep] = raw
    print(f"[search] ASR 数据: {sum(len(v) for v in asr_data.values())} 条, 覆盖 EP {sorted(asr_data.keys())}")

elif _project_type == "interview":
    # 语义索引（ASR 文本）
    if INDEX_NPY.exists() and INDEX_META.exists():
        semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
        semantic_metas = json.load(open(INDEX_META))
        print(f"[search] 口播语义索引: {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")

    # 加载 ASR 转写（按文件）
    interview_asr = {}
    for f in SOURCES_DIR.glob("asr_*.json"):
        key = f.stem.replace("asr_", "")
        interview_asr[key] = json.load(open(f))
    print(f"[search] 口播ASR: {sum(len(v) for v in interview_asr.values())} 条, {len(interview_asr)} 个素材")

# ── Handler ──
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._cached_body = None  # 必须在 super().__init__ 之前，因为父类 __init__ 会触发 handle()
        super().__init__(*args, directory=str(TASK_DIR), **kwargs)

    def _resolve_task_dir(self, task_name=None):
        """解析任务目录：优先 ?task= 参数，否则用启动默认"""
        name = task_name or _args.task
        return PROJECT_DIR / "tasks" / name

    def _resolve_clip_dir(self, task_name=None):
        return self._resolve_task_dir(task_name) / "素材clips"

    def _resolve_work_dir(self, task_name=None):
        return self._resolve_task_dir(task_name) / "work_dir"

    def _get_task_param(self):
        """从请求中提取 task 参数"""
        # GET: 从 query string
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        task = params.get("task", [None])[0]
        if task:
            return task
        # POST: 从缓存的 body
        if self.command == "POST" and self._cached_body:
            try:
                data = json.loads(self._cached_body)
                return data.get("task")
            except Exception:
                pass
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        params = parse_qs(parsed.query)

        # 解析 task 参数（用于动态路由）
        req_task = params.get("task", [None])[0]

        if path == "/search":
            q = params.get("q", [""])[0]
            mode = params.get("mode", ["hybrid"])[0]
            self._json(self._search(q, mode=mode))
        elif path == "/tasks/文案脚本.json":
            task = req_task or _args.task
            script_file = self._resolve_task_dir(task) / "文案脚本.json"
            # also check project-level tasks dir
            if not script_file.exists():
                script_file = PROJECT_DIR / "tasks" / "文案脚本.json"
            if script_file.exists():
                self._json(json.load(open(script_file)))
            else:
                self._json({"ok": False, "error": "文案脚本尚未生成"}, 404)
        elif path == "/segments.json":
            task = req_task or _args.task
            drama_id = db.get_drama_id(_project_name)
            if drama_id:
                task_obj = db.get_task(drama_id, task)
                if task_obj:
                    segments = db.get_task_segments(task_obj["id"])
                    self._json({"segments": segments, "total_segments": len(segments)})
                    return
            # fallback: 从文件读取
            seg_file = self._resolve_task_dir(task) / "segments.json"
            if seg_file.exists():
                self._json(json.load(open(seg_file)))
            else:
                self._json({"segments": [], "total_segments": 0})
        elif path == "/preview_video":
            task = req_task or _args.task
            end_str = params.get("end", [None])[0]
            end_t = float(end_str) if end_str else None
            self._serve_preview(params.get("ep",["1"])[0], float(params.get("t",["0"])[0]),
                               params.get("sid",["default"])[0], task=task, end_t=end_t)
        elif path == "/asr/raw":
            self._handle_asr_raw()
        elif path == "/asr/classified":
            self._handle_asr_classified()
        elif path == "/data/segmented":
            proj = params.get("project", [_project_name])[0]
            seg_file = BASE_DIR / proj / "sources_clean" / "segmented.json"
            if seg_file.exists():
                self._json(json.load(open(seg_file)))
            else:
                self._json({}, 404)
        elif path == "/status":
            task = req_task or _args.task
            self._json({"ok": True, "drama": _project_name, "task": task})
        elif path == "/picks":
            task = req_task or _args.task
            drama_id = db.get_drama_id(_project_name)
            if drama_id:
                picks = db.get_picks(drama_id, task)
                self._json({"picks": picks})
            else:
                self._json({"picks": {}})
        elif path == "/data/quality":
            proj = params.get("project", [_project_name])[0]
            drama_id = db.get_drama_id(proj)
            if drama_id:
                eps = db.get_all_episodes(drama_id)
                summary = db.get_episodes_summary(drama_id)
                reports = db.get_all_quality_reports(drama_id)
                self._json({"episodes": eps, "summary": summary, "reports": reports, "project": proj})
            else:
                self._json({"episodes": [], "summary": {}, "reports": [], "project": proj})
        elif path == "/data/task_check":
            task = req_task or _args.task
            proj = params.get("project", [_project_name])[0]
            drama_id = db.get_drama_id(proj)
            if drama_id:
                task_obj = db.get_task(drama_id, task)
                if task_obj:
                    markers = db.validate_episode_markers(task_obj["id"])
                    self._json({"task": task, "markers": markers})
                    return
            self._json({"task": task, "markers": []})
        elif path == "/data/process_status":
            task_id = params.get("task_id", [None])[0]
            if task_id and task_id in _process_tasks:
                with _process_lock:
                    task = dict(_process_tasks[task_id])
                self._json(task)
            else:
                self._json({"error": "task not found"}, 404)
        elif path == "/dramas":
            self._json(self._list_dramas())
        elif path == "/tasks":
            drama = params.get("drama", [_project_name])[0]
            self._json(self._list_tasks(drama))
        elif path == "/download":
            # 轮询提取状态
            task = req_task or _args.task
            clip_dir = self._resolve_clip_dir(task)
            file_name = params.get("file", [None])[0]
            if file_name and (clip_dir / file_name).exists():
                self._json({"ok": True, "ready": True, "url": f"/clips/{file_name}?task={task}"})
            else:
                self._json({"ok": True, "ready": False})
        elif path == "/proxies/manifest":
            self._serve_proxy_manifest()
        elif "/proxies/" in path:
            self._serve_proxy(path)
        elif "/posters/" in path:
            self._serve_poster(path)
        elif "/素材clips/" in path or "/clips/" in path or "/tts_segments/" in path or "/export_clips/" in path:
            self._serve_clip(req_task)
        else:
            # 1) 优先尝试 serve 前端生产构建 (SPA)
            if self._serve_frontend(path):
                return
            # 2) 兜底：任务目录静态文件
            self._serve_static(req_task)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        req_task = params.get("task", [None])[0] or _args.task

        if path == "/dialogue_match":
            self._handle_dialogue_match()
        elif path == "/chat":
            self._handle_chat()
        elif path == "/assign":
            clip_dir = self._resolve_clip_dir(req_task)
            data = json.loads(self._read_body())
            # 如果有pv_file → 复制预览文件; 否则 → 重新编码
            if data.get("pv_file"):
                import shutil
                src = clip_dir / data["pv_file"]
                dst_name = f"clip_pick_S{data.get('sid','0')}_{data.get('seq','0')}_{data.get('type','main')}_ep{data.get('ep','0')}.mp4"
                dst = clip_dir / dst_name
                shutil.copy(str(src), str(dst))
                thumb = clip_dir / (dst_name.rsplit('.',1)[0]+'.jpg')
                mid = float(data.get("start",0)) + (float(data.get("end",0))-float(data.get("start",0)))/2
                subprocess.run(["ffmpeg","-y","-ss",str(mid),"-i",
                    str(SOURCE_VIDEOS.get(f'ep{data.get("ep",27)}','')),"-vframes","1","-q:v","3",str(thumb)], capture_output=True)
                self._json({"ok":True, "file":dst_name, "thumb":thumb.name})
            else:
                result = self._extract(data, full=True, clip_dir=clip_dir)
                self._json(result)
        elif path == "/copy":
            # 将临时预览文件复制为正式命名文件（避免重新编码，添加/补充镜头时调用）
            import shutil
            clip_dir = self._resolve_clip_dir(req_task)
            data = json.loads(self._read_body())
            pv_file = data.get("pv_file", "")
            src = clip_dir / pv_file
            if not pv_file or not src.exists():
                self._json({"ok": False, "error": f"pv_file not found: {pv_file}"}, 404)
                return
            sid = data.get("sid", "0")
            seq = data.get("seq", "0")
            ptype = data.get("type", "main")
            ep = data.get("ep", "0")
            dst_name = f"clip_pick_S{sid}_{seq}_{ptype}_ep{ep}.mp4"
            dst = clip_dir / dst_name
            shutil.copy(str(src), str(dst))
            thumb_name = dst_name.rsplit(".", 1)[0] + ".jpg"
            thumb = clip_dir / thumb_name
            mid = float(data.get("start", 0)) + (float(data.get("end", 0)) - float(data.get("start", 0))) / 2
            src_video = SOURCE_VIDEOS.get(f"ep{ep}", "")
            if src_video:
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(mid), "-i", str(src_video),
                     "-vframes", "1", "-q:v", "3", str(thumb)],
                    capture_output=True)
            self._json({"ok": True, "file": dst_name, "thumb": thumb_name})
        elif path == "/thumb":
            clip_dir = self._resolve_clip_dir(req_task)
            data = json.loads(self._read_body())
            result = self._thumb(data, clip_dir=clip_dir)
            self._json(result)
        elif path == "/download":
            self._handle_download(req_task)
        elif path == "/storyboard_suggest":
            data = json.loads(self._read_body())
            suggestions = self._generate_storyboard(data.get("narration", ""))
            self._json({"suggestions": suggestions})
        elif path == "/tasks/create":
            self._create_task()
        elif path == "/data/process":
            data = json.loads(self._read_body())
            proj = data.get("project", _project_name)
            # 检查项目类型
            proj_type = _project_type
            cfg_path = BASE_DIR / "projects" / f"{proj}.json"
            if cfg_path.exists():
                proj_type = json.load(open(cfg_path)).get("type", "drama")
            # 口播采访流水线
            if proj_type == "interview":
                task_id = f"intv_{int(time.time())}"
                threading.Thread(
                    target=_run_interview_pipeline,
                    args=(task_id, proj, data.get("step", "all")),
                    daemon=True,
                ).start()
                self._json({"ok": True, "task_id": task_id})
                return
            # 电视剧流水线
            episodes = data.get("episodes", [])
            if not episodes:
                self._json({"ok": False, "error": "请指定集数"}, 400)
                return
            task_id = f"proc_{int(time.time())}"
            threading.Thread(
                target=_run_pipeline,
                args=(task_id, episodes, proj),
                daemon=True,
            ).start()
            self._json({"ok": True, "task_id": task_id})
        elif path == "/picks":
            data = json.loads(self._read_body())
            drama_id = db.get_drama_id(_project_name)
            if drama_id:
                db.save_picks(drama_id, req_task, data.get("picks", {}))
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "drama not found"}, 404)
        elif path == "/export/extract_clips":
            self._handle_export_extract(req_task)
        elif path == "/script/analyze_transcript":
            self._handle_analyze_transcript()
        elif path == "/script/generate_from_outline":
            self._handle_generate_from_outline()
        elif path == "/script/generate_script":
            self._handle_generate_script()
        elif path == "/script/generate_script_stream":
            self._handle_generate_script_stream()
        elif path == "/script/generate_story_first":
            self._handle_generate_story_first()
        elif path == "/asr/raw":
            self._handle_asr_raw()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _search(self, query, limit=10, mode="hybrid", eps=None, boost_eps=None):
        if not query: return []

        # 口播项目: 添加基于 classified ASR 的关键词搜索
        if _project_type == "interview" and mode in ("keyword", "hybrid"):
            kw_results = self._interview_keyword_search(query, limit)
            if mode == "keyword":
                return kw_results
            # hybrid: 合并关键词+语义
            sem_results = self._semantic_search(query, limit)
            return self._merge_results(kw_results, sem_results, limit)

        if mode == "keyword":
            results = self._keyword_search(query, limit)
        elif mode == "semantic":
            results = self._semantic_search(query, limit)
        elif mode == "hybrid":
            results = self._hybrid_search(query, limit)
        elif mode == "deep":
            results = self._deep_search(query, limit)
        elif mode == "asr_first":
            results = self._asr_first_search(query, limit)
        else:
            results = self._hybrid_search(query, limit)
        # 剧集过滤 / 加权
        if eps:
            ep_set = set(int(e) for e in str(eps).split(",") if e.strip().isdigit())
            if ep_set:
                # 先筛选优先剧集，再拼接其他结果
                priority = [r for r in results if r.get("ep") in ep_set]
                others = [r for r in results if r.get("ep") not in ep_set]
                results = priority + others
        return results

    def _interview_keyword_search(self, query, limit=10):
        '''口播项目: 在 classified ASR 中做纯关键词搜索'''
        results = {}
        q_clean = _norm(query)
        qlen = len(q_clean)

        # n-gram scoring
        kws = {}
        for n in range(2, min(qlen + 1, 9)):
            w = 3 ** (n - 2) if n <= 5 else 27
            seen = set()
            for i in range(qlen - n + 1):
                kw = q_clean[i:i+n]
                if kw not in seen:
                    seen.add(kw)
                    kws[kw] = max(kws.get(kw, 0), w)
        if qlen > 1:
            kws[q_clean] = 81  # 完整 query 最高权重

        # Search classified ASR
        cf = PROJECT_DIR / "sources_clean" / "classified_学习新东方.json"
        if cf.exists():
            classified = json.load(open(cf))
            for s in classified:
                text = _norm(s.get('text', ''))
                score = sum(text.count(kw) * w for kw, w in kws.items())
                if score <= 0: continue
                k = f"{s.get('start_sec',0):.0f}"
                r = {
                    "ep": 0, "start": s.get('start_sec', 0), "end": s.get('start_sec', 0) + 3,
                    "scene_id": 0, "description": text[:200], "asr": text[:200],
                    "score": round(score * 1.5, 1),
                    "duration": 3, "source": "学习新东方",
                }
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r

        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    def _merge_results(self, kw_results, sem_results, limit=10):
        '''合并关键词和语义搜索结果'''
        merged = {}
        max_kw = max((r["score"] for r in kw_results), default=1)
        for r in kw_results:
            k = f"{r.get('source','')}_{r['start']:.0f}"
            merged[k] = {**r, "score": r["score"] / max_kw * 40}  # 关键词 0-40

        max_sem = max((r["score"] for r in sem_results), default=1)
        for r in sem_results:
            k = f"{r.get('source','')}_{r['start']:.0f}"
            sem_score = r["score"] / max_sem * 60  # 语义 0-60
            if k in merged:
                merged[k]["score"] += sem_score
            else:
                merged[k] = {**r, "score": sem_score}

        return sorted(merged.values(), key=lambda x: -x["score"])[:limit]

    def _asr_first_search(self, query, limit=10):
        '''ASR优先匹配：纯 ASR 关键词搜索 + 语义兜底，结果展示 ASR 台词'''
        query = _norm(query)  # 繁→简归一化
        results = {}

        # Step 1: ASR 关键词搜索（加权 n-gram，不含 VLM）
        kws = {}  # 复刻 _keyword_search 的加权逻辑，但只搜 ASR
        qlen = len(query)
        for n in range(2, min(qlen + 1, 9)):
            w = 3 ** (n - 2) if n <= 5 else 27
            seen = set()
            for i in range(qlen - n + 1):
                kw = query[i:i+n]
                if kw not in seen:
                    seen.add(kw)
                    kws[kw] = max(kws.get(kw, 0), w)
        if qlen > 4:
            kws[query] = 81

        for ep in sorted(asr_data.keys()):
            asr_list = asr_data.get(ep, [])
            for i, a in enumerate(asr_list):
                asr_text = a["text"]
                score = sum(asr_text.count(kw) * w for kw, w in kws.items())
                if score <= 0: continue
                start, end, text = a["start"], a["end"], asr_text
                # 合并前后匹配片段（扩展对话上下文）
                if i > 0 and sum(asr_list[i-1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    start = asr_list[i-1]["start"]; text = asr_list[i-1]["text"] + " " + text
                if i > 1 and sum(asr_list[i-2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    start = asr_list[i-2]["start"]; text = asr_list[i-2]["text"] + " " + text
                if i+1 < len(asr_list) and sum(asr_list[i+1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    end = asr_list[i+1]["end"]; text += " " + asr_list[i+1]["text"]
                if i+2 < len(asr_list) and sum(asr_list[i+2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    end = asr_list[i+2]["end"]; text += " " + asr_list[i+2]["text"]
                # ASR 匹配得分加权
                score = min(score * 1.5, 95)
                k = f"{ep}_{start:.0f}"
                r = self._make_result(ep, start, end, 0, text[:200], text[:200], score)
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r

        # Step 2: 语义兜底（只补不足的部分，且用 ASR 台词替换描述）
        if len(results) < limit:
            seen = set(results.keys())
            semantic = self._semantic_search(query, 20)
            for r in semantic:
                k = f"{r['ep']}_{r['start']:.0f}"
                if k in seen: continue
                # 查找该时间段的 ASR 台词
                ep = r["ep"]
                asr_txt = ""
                for a in asr_data.get(ep, []):
                    if a["start"] < r["end"] and a["end"] > r["start"]:
                        asr_txt += a["text"]
                # 用 ASR 台词替换 VLM 描述，降权
                if asr_txt:
                    r["description"] = asr_txt[:200]
                    r["asr"] = asr_txt[:200]
                r["score"] = r["score"] * 0.4  # 语义兜底大幅降权
                results[k] = r
                seen.add(k)

        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    def _semantic_search(self, query, limit=10):
        '''纯语义搜索（BGE embedding + 余弦相似度）'''
        if semantic_emb is None: return []
        emb = semantic_emb
        metas = semantic_metas
        q_emb = _encode(query)
        scores = np.dot(emb, q_emb)
        top = np.argsort(scores)[-30:][::-1]
        results = {}

        # 口播模式
        if _project_type == "interview":
            for i in top:
                if scores[i] <= 0.30: continue
                m = metas[i]
                r = {
                    "ep": 0, "start": m["start"], "end": m["end"],
                    "scene_id": 0, "description": m["text"][:200], "asr": m["text"][:200],
                    "source": m.get("source", ""),
                    "score": round(float(scores[i]) * 100, 1),
                    "duration": round(m["end"] - m["start"], 1),
                }
                k = f"{m['source']}_{m['start']:.0f}"
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r
            return sorted(results.values(), key=lambda x: -x["score"])[:limit]

        # 电视剧模式
        for i in top:
            if scores[i] <= 0.35: continue
            m = metas[i]
            asr_txt = ""
            for a in asr_data.get(m["ep"], []):
                if a["start"] < m["end"] and a["end"] > m["start"]:
                    asr_txt += a["text"]
            r = self._make_result(m["ep"], m["start"], m["end"],
                m.get("scene_id", 0), m["text"][:200], asr_txt[:200],
                round(float(scores[i]) * 50, 1))
            k = f"{m['ep']}_{m['start']:.0f}"
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r
        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    def _keyword_search(self, query, limit=10):
        '''关键词搜索（ASR + VLM 词频匹配），使用加权 n-gram'''
        results = {}
        # 加权 n-gram：越长权重越高，鼓励连续匹配
        # 权重: 2-gram=1, 3-gram=3, 4-gram=9, 5+=27
        kws = {}  # {keyword: weight}
        qlen = len(query)
        for n in range(2, min(qlen + 1, 9)):
            w = 3 ** (n - 2) if n <= 5 else 27  # 权重指数增长，5+封顶
            seen = set()
            for i in range(qlen - n + 1):
                kw = query[i:i+n]
                if kw not in seen:
                    seen.add(kw)
                    kws[kw] = max(kws.get(kw, 0), w)
        # 完整 query 作为最高权重关键词
        if qlen > 4:
            kws[query] = 81

        # ASR 关键词匹配（加权得分）
        for ep in sorted(asr_data.keys()):
            asr_list = asr_data.get(ep, [])
            for i, a in enumerate(asr_list):
                asr_text = a["text"]
                score = sum(asr_text.count(kw) * w for kw, w in kws.items())
                if score <= 0: continue
                start, end, text = a["start"], a["end"], asr_text
                # 合并前后匹配的相邻片段（扩展上下文）
                merged = 0
                if i > 0 and sum(asr_list[i-1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    start = asr_list[i-1]["start"]; text = asr_list[i-1]["text"] + " " + text
                    merged += 1
                if i > 1 and sum(asr_list[i-2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    start = asr_list[i-2]["start"]; text = asr_list[i-2]["text"] + " " + text
                    merged += 1
                if i+1 < len(asr_list) and sum(asr_list[i+1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    end = asr_list[i+1]["end"]; text += " " + asr_list[i+1]["text"]
                    merged += 1
                if i+2 < len(asr_list) and sum(asr_list[i+2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                    end = asr_list[i+2]["end"]; text += " " + asr_list[i+2]["text"]
                # 合并奖励
                score += merged * 5
                k = f"{ep}_{start:.0f}_kw"
                r = self._make_result(ep, start, end, 0, text[:200], "", score)
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r

        # VLM 描述关键词匹配
        for s in vlm_data:
            desc = s.get("description","")
            score = sum(desc.count(kw) * w * 3 for kw, w in kws.items())
            if score <= 0: continue
            k = f"{s['_ep']}_{s['start']:.0f}"
            r = self._make_result(s["_ep"], s["start"], s["end"],
                s["scene_id"], desc[:200], "", score)
            if k in results: r["score"] += results[k]["score"]
            results[k] = r
        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    def _hybrid_search(self, query, limit=10):
        '''混合检索：语义(0.7) + 关键词(0.3) 加权融合'''
        semantic_results = self._semantic_search(query, 30)
        keyword_results = self._keyword_search(query, 30)
        
        # 归一化 + 加权合并
        merged = {}
        # 语义结果
        max_s = max((r["score"] for r in semantic_results), default=1)
        for r in semantic_results:
            k = f"{r['ep']}_{r['start']:.0f}"
            merged[k] = {**r, "score": r["score"] / max_s * 70}  # 0-70
        
        # 关键词结果
        max_k = max((r["score"] for r in keyword_results), default=1)
        for r in keyword_results:
            k = f"{r['ep']}_{r['start']:.0f}"
            kw_score = r["score"] / max_k * 30  # 0-30
            if k in merged:
                merged[k]["score"] += kw_score
            else:
                merged[k] = {**r, "score": kw_score}
        
        return sorted(merged.values(), key=lambda x: -x["score"])[:limit]

    def _deep_search(self, query, limit=10):
        '''深度搜索：Query扩展 + 混合检索 + LLM重排'''
        # Step 1: Query 扩展
        variants = self._expand_query(query)
        # Step 2: 混合检索（每个变体搜一次，取并集）
        all_hits = {}
        for q in [query] + variants:
            for r in self._hybrid_search(q, 20):
                k = f"{r['ep']}_{r['start']:.0f}"
                if k not in all_hits or r["score"] > all_hits[k]["score"]:
                    all_hits[k] = r
        # Step 3: 取 Top 20 候选
        candidates = sorted(all_hits.values(), key=lambda x: -x["score"])[:20]
        if len(candidates) <= limit: return candidates
        
        # Step 4: LLM 重排
        return self._llm_rerank(query, candidates, limit)

    def _expand_query(self, query):
        '''LLM 扩展查询：生成2-3个不同角度的搜索词'''
        import urllib.request as _ur
        api_key = os.environ.get("MIMO_API_KEY", "")
        api_url = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
        payload = json.dumps({
            "model": "mimo-v2.5",
            "messages": [{
                "role": "system",
                "content": "将用户的分镜描述改写为2-3个具体的画面搜索关键词（每行一个，10-20字），用于搜索视频素材库。直接输出关键词，不要编号。"
            }, {
                "role": "user",
                "content": f"分镜描述：{query}"
            }],
            "max_tokens": 200,
        }).encode("utf-8")
        req = _ur.Request(
            f"{api_url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with _ur.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return [l.strip().lstrip("- 123456789.）)") for l in text.strip().split("\n") if l.strip()][:3]
        except Exception as e:
            print(f"[expand_query] failed: {e}")
            return []

    def _llm_rerank(self, query, candidates, top_n=10):
        '''LLM 对候选画面重排序'''
        import urllib.request as _ur
        api_key = os.environ.get("MIMO_API_KEY", "")
        api_url = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
        
        # 准备候选列表
        cand_text = "\n".join(
            f"[{i}] EP{c['ep']} {c['start']:.0f}s-{c['end']:.0f}s | {c['description'][:120]}"
            for i, c in enumerate(candidates)
        )
        payload = json.dumps({
            "model": "mimo-v2.5",
            "messages": [{
                "role": "system",
                "content": "你是视频素材匹配助手。根据分镜描述的画面内容，对候选素材进行相关性排序。只输出最相关的5-10个编号（如：3,7,1,12,5），不要解释。"
            }, {
                "role": "user",
                "content": f"分镜描述：{query}\n\n候选素材：\n{cand_text}\n\n请选出最相关的素材编号（逗号分隔）："
            }],
            "max_tokens": 100,
        }).encode("utf-8")
        req = _ur.Request(
            f"{api_url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with _ur.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 解析编号
            ids = [int(s.strip()) for s in re.findall(r'\d+', text) if s.strip().isdigit()]
            reranked = [candidates[i] for i in ids if 0 <= i < len(candidates)]
            return reranked[:top_n] if reranked else candidates[:top_n]
        except Exception as e:
            print(f"[llm_rerank] failed: {e}")
            return candidates[:top_n]

    def _make_result(self, ep, start, end, scene_id, desc, asr, score):
        return {
            "ep": ep, "start": start, "end": end,
            "scene_id": scene_id,
            "duration": round(end - start, 1),
            "description": desc, "asr": asr,
            "score": round(score, 1),
        }

    def _extract(self, data, full=False, clip_dir=None):
        if clip_dir is None:
            clip_dir = CLIP_DIR  # backward compat
        ep = data["ep"]; start=max(0,float(data["start"])-2); end=float(data["end"])+2
        src = SOURCE_VIDEOS.get(f"ep{ep}")
        if not src: return {"error":"src not found"}
        name = f"clip_search_ep{ep}_{int(start)}s.mp4"
        out = clip_dir / name
        if full:
            subprocess.run(["ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(end-start),
                "-c:v","libx264","-preset","ultrafast","-crf","23","-c:a","aac","-b:a","192k",
                str(out)], capture_output=True)
        # 缩略图
        thumb = clip_dir / (name.rsplit('.',1)[0]+'.jpg')
        mid = start + (end-start)/2
        subprocess.run(["ffmpeg","-y","-ss",str(mid),"-i",str(src),"-vframes","1","-q:v","3",str(thumb)],
            capture_output=True)
        result = {"ok":True, "duration":round(end-start,1), "thumb":thumb.name}
        if full: result["file"] = name
        return result

    def _thumb(self, data, clip_dir=None):
        return self._extract(data, full=False, clip_dir=clip_dir)

    def _handle_download(self, req_task):
        """POST /download — 提取高清片段供下载"""
        clip_dir = self._resolve_clip_dir(req_task)
        data = json.loads(self._read_body())
        ep = str(data.get("ep", "1"))
        start = float(data.get("start", 0))
        end = float(data.get("end", 0))
        src = SOURCE_VIDEOS.get(f"ep{ep}")
        if not src:
            self._json({"ok": False, "error": "源视频未找到"}, 404)
            return
        # 可读文件名：clip_EP1_19m05s_to_19m07s.mp4
        def fmt(sec):
            m, s = int(sec // 60), int(sec % 60)
            return f"{m}m{s:02d}s"
        name = f"clip_EP{ep}_{fmt(start)}_to_{fmt(end)}.mp4"
        out = clip_dir / name
        if out.exists():
            # 已存在则直接返回
            self._json({"ok": True, "file": name, "url": f"/clips/{name}?task={req_task}", "cached": True})
            return
        # ffmpeg 高清提取（preset=fast, crf=20 平衡速度与质量）
        self._json({"ok": True, "file": name, "status": "extracting"})  # 先返回，避免超时
        # 后台提取
        import threading
        def extract():
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start), "-i", str(src),
                "-t", str(end - start),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "256k",
                str(out)
            ], capture_output=True)
        threading.Thread(target=extract, daemon=True).start()

    def _serve_preview(self, ep, t, sid="default", task=None, end_t=None):
        task_name = task or _args.task
        clip_dir = self._resolve_clip_dir(task_name)
        src = SOURCE_VIDEOS.get(f"ep{ep}")
        if not src: return self.send_error(404)
        tmp = clip_dir / f"_pv_{sid}.mp4"
        if end_t and end_t > t:
            # 用户指定了起止时间 → 按输入范围剪辑
            clip_start = max(0, t - 1)
            clip_end = end_t + 1
            duration = clip_end - clip_start
        else:
            # 默认：20 秒预览窗口
            clip_start = max(0, t - 2)
            clip_end = clip_start + 20
            duration = 20
        subprocess.run(["ffmpeg","-y","-ss",str(clip_start),"-i",str(src),
            "-t",str(duration),"-vf","scale=640:360","-c:v","libx264","-preset","ultrafast",
            "-crf","28","-c:a","aac","-b:a","64k",str(tmp)], capture_output=True)
        if tmp.exists():
            url = f"/clips/{tmp.name}?task={task_name}"
            self._json({"ok":True, "file":tmp.name, "url":url,
                "start":clip_start, "end":clip_end})
        else:
            self.send_error(500)

    def _serve_poster(self, path):
        """Serve poster images. URL: /posters/<drama>/cover.jpg → <drama>/posters/cover.jpg"""
        parts = unquote(path).strip("/").split("/")
        if len(parts) >= 3:
            drama_name = parts[1]
            filename = parts[2]
            file_path = BASE_DIR / drama_name / "posters" / filename
            if file_path.exists():
                self._send_file(file_path, "image/jpeg")
                return
        return self.send_error(404)

    def _serve_proxy_manifest(self):
        """GET /proxies/manifest → 返回 .proxies_manifest.json"""
        if PROXY_MANIFEST.exists():
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(PROXY_MANIFEST.read_bytes())
        else:
            self._json({"drama": _project_name, "proxies": [], "note": "无代理文件，请先运行 generate_proxies.py"})

    def _serve_proxy(self, path):
        """Serve 代理视频文件，支持 HTTP Range 请求"""
        clean = unquote(path).lstrip("/")
        # /proxies/都挺好_01_540p.mp4 → <drama>/proxies/都挺好_01_540p.mp4
        filename = clean.split("/")[-1]
        file_path = PROXY_DIR / filename
        if not file_path.exists():
            return self.send_error(404)

        size = file_path.stat().st_size
        rh = self.headers.get("Range")
        if rh:
            start, end = 0, size - 1
            m = rh.replace("bytes=", "").split("-")
            start = int(m[0]) if m[0] else 0
            end = int(m[1]) if len(m) > 1 and m[1] else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            length = end - start + 1
        else:
            start, end, length = 0, size - 1, size
            self.send_response(200)

        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle_export_extract(self, task_name):
        """POST /export/extract_clips — 从 1080p 原剧批量提取 clip 片段用于导出"""
        import tempfile, os

        data = json.loads(self._read_body())
        clips = data.get("clips", [])
        if not clips:
            self._json({"ok": False, "error": "no clips provided"}, 400)
            return

        # 按剧集分组
        by_ep = {}
        for c in clips:
            ep = c["ep"]
            if ep not in by_ep:
                by_ep[ep] = []
            by_ep[ep].append(c)

        # 输出目录
        task_dir = self._resolve_task_dir(task_name)
        export_dir = task_dir / "export_clips"
        export_dir.mkdir(exist_ok=True)

        extracted = []
        for ep, ep_clips in sorted(by_ep.items()):
            src_key = f"ep{ep}"
            if src_key not in SOURCE_VIDEOS:
                print(f"[export] 未找到 EP{ep} 源视频")
                continue

            src_path = SOURCE_VIDEOS[src_key]
            for i, c in enumerate(ep_clips):
                out_name = c.get("outputName", f"ep{ep}_clip{i:03d}.mp4")
                out_path = export_dir / out_name

                # 跳过已存在的
                if out_path.exists() and not c.get("overwrite"):
                    extracted.append({
                        "ep": ep, "outputName": out_name,
                        "url": f"/export_clips/{out_name}?task={task_name}",
                    })
                    continue

                start = c["start"]
                dur = c["end"] - c["start"]

                cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(start), "-t", str(dur),
                    "-i", str(src_path),
                    "-c", "copy",  # 无损复制，不从代理转码
                    "-avoid_negative_ts", "make_zero",
                    str(out_path),
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0 and out_path.exists():
                    extracted.append({
                        "ep": ep, "outputName": out_name,
                        "url": f"/export_clips/{out_name}?task={task_name}",
                        "duration": dur,
                    })
                    print(f"[export] EP{ep} {start}s-{c['end']}s → {out_name}")
                else:
                    print(f"[export] EP{ep} 提取失败: {result.stderr[:200]}")

        self._json({"ok": True, "clips": extracted, "total": len(extracted)})

    def _send_file(self, file_path, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", file_path.stat().st_size)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())
        self.send_response(200)
        ext = file_path.suffix.lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png" if ext == ".png" else "image/webp"
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", file_path.stat().st_size)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def _create_task(self):
        """POST /tasks/create — 创建任务目录 + 处理解说素材"""
        import shutil, traceback

        # 解析 multipart 或 JSON
        content_type = self.headers.get("Content-Type", "")
        data = {}
        docx_bytes = None
        audio_bytes = None
        docx_name = "解说文案.docx"
        audio_name = "解说音频.wav"

        if "application/json" in content_type:
            data = json.loads(self._read_body())
        elif "multipart/form-data" in content_type:
            # 简单 multipart 解析
            body = self._read_body()
            boundary = content_type.split("boundary=")[1].strip()
            parts = body.split(("--" + boundary).encode())
            for part in parts:
                if b"Content-Disposition" not in part:
                    continue
                header_end = part.find(b"\r\n\r\n")
                if header_end < 0:
                    continue
                header = part[:header_end].decode("utf-8", errors="ignore")
                content = part[header_end + 4:]
                if content.endswith(b"\r\n"):
                    content = content[:-2]
                if 'name="drama"' in header:
                    data["drama"] = content.decode("utf-8", errors="ignore").strip()
                elif 'name="name"' in header:
                    data["name"] = content.decode("utf-8", errors="ignore").strip()
                elif 'name="local_path"' in header:
                    data["local_path"] = content.decode("utf-8", errors="ignore").strip()
                elif 'name="docx"' in header or 'filename="' in header and '.docx' in header:
                    docx_bytes = content
                    # extract filename
                    import re as _re
                    fm = _re.search(r'filename="([^"]+)"', header)
                    if fm: docx_name = fm.group(1)
                elif 'name="audio"' in header or ('filename="' in header and ('.wav' in header or '.mp3' in header)):
                    audio_bytes = content
                    import re as _re
                    fm = _re.search(r'filename="([^"]+)"', header)
                    if fm: audio_name = fm.group(1)

        drama_name = data.get("drama", _project_name)
        task_name = data.get("name", "").strip()
        local_path = data.get("local_path", "").strip()

        if not task_name:
            self._json({"ok": False, "error": "缺少任务名称"}, 400)
            return

        task_dir = BASE_DIR / drama_name / "tasks" / task_name
        if task_dir.exists():
            self._json({"ok": False, "error": f"任务目录已存在: {task_dir}"}, 400)
            return

        try:
            task_dir.mkdir(parents=True)
            (task_dir / "work_dir").mkdir()
            (task_dir / "素材clips").mkdir()

            # 模式1: 从本地路径复制文件
            if local_path:
                src_dir = Path(local_path)
                if not src_dir.exists():
                    self._json({"ok": False, "error": f"源目录不存在: {local_path}"}, 400)
                    return
                # 找 docx 和音频文件
                for f in src_dir.iterdir():
                    if f.suffix == ".docx":
                        shutil.copy(f, task_dir / "解说文案.docx")
                    elif f.suffix in (".wav", ".mp3"):
                        shutil.copy(f, task_dir / f"解说音频{f.suffix}")
            # 模式2: 上传文件
            else:
                if docx_bytes:
                    (task_dir / docx_name).write_bytes(docx_bytes)
                if audio_bytes:
                    (task_dir / audio_name).write_bytes(audio_bytes)

            # 检查是否有解说文案
            docx_file = task_dir / "解说文案.docx"
            if not docx_file.exists():
                self._json({"ok": False, "error": "未找到解说文案.docx"}, 400)
                return

            # 运行处理流水线
            results = {"ok": True, "task": task_name, "steps": []}

            # A1: 解析文案
            import subprocess as _sp
            env = {**__import__("os").environ, "VIBECAP_DRAMA": drama_name, "VIBECAP_TASK": task_name}
            r = _sp.run(["/opt/anaconda3/bin/python3", str(Path(__file__).parent / "parse_docx.py")],
                       capture_output=True, text=True, env=env, timeout=60)
            results["steps"].append({"step": "parse_docx", "ok": r.returncode == 0, "output": r.stdout[-200:]})

            # 同步到 SQLite
            drama_id = db.get_drama_id(drama_name)
            if not drama_id:
                drama_id = db.ensure_drama(drama_name)
            if drama_id:
                task_id = db.create_task(drama_id, task_name)
                if r.returncode == 0 and (task_dir / "segments.json").exists():
                    seg_data = json.load(open(task_dir / "segments.json"))
                    segs = seg_data.get("segments", [])
                    db.save_task_segments(task_id, segs)

            if r.returncode == 0 and (task_dir / "segments.json").exists():
                # A2: ASR 解说音频
                audio_file = task_dir / "解说音频.wav"
                if audio_file.exists():
                    r2 = _sp.run(["/opt/anaconda3/bin/python3", str(Path(__file__).parent / "asr_narration.py")],
                               capture_output=True, text=True, env=env, timeout=300)
                    results["steps"].append({"step": "asr_narration", "ok": r2.returncode == 0, "output": r2.stdout[-200:]})

                    # A3: 匹配切分
                    if r2.returncode == 0:
                        r3 = _sp.run(["/opt/anaconda3/bin/python3", str(Path(__file__).parent / "match_split.py")],
                                   capture_output=True, text=True, env=env, timeout=60)
                        results["steps"].append({"step": "match_split", "ok": r3.returncode == 0, "output": r3.stdout[-200:]})

            self._json(results)

        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)}, 500)

    def _list_dramas(self):
        """列出所有项目（SQLite + 文件系统 projects/*.json）"""
        dramas = db.list_dramas()
        seen = {d["name"] for d in dramas}
        projects_dir = BASE_DIR / "projects"
        if projects_dir.exists():
            for cfg_file in sorted(projects_dir.glob("*.json")):
                name = cfg_file.stem
                if name in seen: continue
                try:
                    cfg = json.load(open(cfg_file))
                    dramas.append({
                        "name": name,
                        "type": cfg.get("type", "drama"),
                        "description": cfg.get("description", ""),
                        "task_count": 0,
                    })
                except Exception: pass
        return dramas

    def _list_tasks(self, drama_name):
        """列出项目的所有任务（SQLite + 文件系统扫描）"""
        tasks = []
        # 1. SQLite
        drama_id = db.get_drama_id(drama_name)
        if drama_id:
            tasks = db.list_tasks(drama_id)
        seen = {t.get("name", "") for t in tasks}
        # 2. 文件系统
        tasks_dir = BASE_DIR / drama_name / "tasks"
        if tasks_dir.exists():
            for task_dir in sorted(tasks_dir.iterdir()):
                if not task_dir.is_dir(): continue
                name = task_dir.name
                if name in seen: continue
                # 读取 segments.json 获取段数
                seg_count = 0
                seg_file = task_dir / "segments.json"
                if seg_file.exists():
                    try:
                        seg_count = len(json.load(open(seg_file)).get("segments", []))
                    except Exception: pass
                tasks.append({
                    "name": name, "status": "editing",
                    "segments": seg_count, "duration": 0,
                })
        return tasks

    # ── 台词匹配 ──

    def _handle_dialogue_match(self):
        """POST /dialogue_match — 拆解台词 + 匹配原剧 ASR"""
        data = json.loads(self._read_body())
        dialogue = data.get("dialogue", "")

        if not dialogue or not dialogue.strip():
            self._json({"lines": []})
            return

        # Step 1: DeepSeek 拆句 + 标准化
        lines = self._dialogue_split_normalize(dialogue)

        # Step 2: 每个变体搜 ASR，选最佳匹配作为标准化结果
        results = []
        for line in lines:
            original = line.get("original", "")
            variants = line.get("variants", [original])
            best_match = None
            best_variant = ""

            for v in variants:
                matches = self._search_asr_text(v, limit=1)
                if matches:
                    m = matches[0]
                    if not best_match or m["score"] > best_match["score"]:
                        best_match = m
                        best_variant = v

            # 关键字得分 ≥ 5 即认为找到匹配（关键词匹配分天然低于 BGE）
            if best_match and best_match["score"] >= 5:
                normalized = best_match["text"][:80]
                confident = True
            else:
                normalized = variants[0] if variants else original
                confident = False

            results.append({
                "original": original,
                "normalized": normalized,
                "confident": confident,
                "variant_used": best_variant,
                "matches": [best_match] if best_match and confident else []
            })

        self._json({"lines": results})

    def _dialogue_split_normalize(self, dialogue):
        """DeepSeek 拆解台词 + 生成多个变体，ASR 验证后选最佳匹配"""
        import urllib.request as _ur

        # Step 1: DeepSeek 拆句 + 生成多个可能说法
        prompt = (
            "你是一个影视台词校对助手。用户给你一段解说脚本中的'高亮台词'，"
            "这段台词可能由多句拼凑而成，且经过了改写，与演员实际说的话不完全一致。\n\n"
            "请完成：\n"
            "1. 把台词拆成独立的对白句（去掉叙述性文字）\n"
            "2. 对每句，生成 3-5 个可能的原剧说法变体——想象演员实际可能怎么说出这句话。"
            "变体要覆盖不同的措辞、语序、省略方式。\n\n"
            '输出 JSON：{"lines":[{"original":"原文","variants":["变体1","变体2","变体3"]}]}\n\n'
            "示例：\n"
            '输入: "爸，你是想跟大哥去美国吧？"\n'
            '输出: {"lines":[{"original":"爸，你是想跟大哥去美国吧？","variants":["你想跟大哥去美国","他跟大哥去美国","他想跟你去美国","你要去美国找大哥","跟大哥去美国是吧"]}]}'
        )

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"高亮台词：{dialogue}\n\n输出JSON："}
            ],
            "temperature": 0.7,
            "max_tokens": 1500,
        }).encode("utf-8")

        try:
            req = _ur.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            with _ur.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"): text = text.split("\n",1)[1].split("```")[0].strip()
            parsed = json.loads(text)
            return parsed.get("lines", [])
        except Exception as e:
            print(f"[dialogue_split] LLM 失败: {e}")
            parts = re.split(r'[。！？?！]', dialogue)
            return [{"original": p.strip(), "variants": [p.strip()]} for p in parts if len(p.strip()) > 2]

    def _search_asr_text(self, query, limit=3):
        """关键字搜索 ASR + 字幕数据（字幕权重 x2）"""
        results = {}
        q_clean = re.sub(r'[，。！？、\s　]', '', query)
        kws = []
        for n in [2, 3]:
            for i in range(len(q_clean) - n + 1):
                kw = q_clean[i:i+n]
                stopwords2 = {'你想','想去','去跟','跟他','他的','她的','一个','这个','那个','什么','怎么','不是','就是','还是','可以','已经','因为','所以','但是','不过','虽然','如果','只是','还不','不了','哪个','那儿'}
                if kw not in stopwords2: kws.append(kw)

        # 搜 ASR 数据
        for ep, asr_list in asr_data.items():
            for a in asr_list:
                text = a["text"]
                score = sum((text.count(k) * 3) for k in kws)
                if score <= 0: continue
                k = f"asr_{ep}_{a['start']:.0f}"
                r = {"ep": ep, "start": a["start"], "end": a["end"], "text": text[:200], "score": score}
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r

        # 搜字幕数据（从 VLM 提取的硬字幕，权重 x2）
        if semantic_metas:
            for i, m in enumerate(semantic_metas):
                if m.get("type") != "sub": continue
                text = m["text"]
                score = sum((text.count(k) * 6) for k in kws)  # 字幕权重 x2
                if score <= 0: continue
                k = f"sub_{m['ep']}_{m['start']:.0f}"
                r = {"ep": m["ep"], "start": m["start"], "end": m["end"], "text": text[:200], "score": score}
                if k not in results or r["score"] > results[k]["score"]:
                    results[k] = r

        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    # ── AI 聊天搜索 ──

    def _handle_chat(self):
        """POST /chat — 对话式素材搜索"""
        data = json.loads(self._read_body())
        messages = data.get("messages", [])
        context = data.get("context", {})
        eps = data.get("eps", None)  # 优先剧集

        if not messages:
            self._json({"reply": "请描述你想找的画面", "results": []})
            return

        # 检测 ASR 优先策略：前端传入 strategy="asr_first" 或 seq="D"（台词）
        strategy = context.get("strategy", "")
        if not strategy and str(context.get("seq", "")) == "D":
            strategy = "asr_first"

        # ── ASR 优先：跳过 AI 精炼，直接用原话搜 ASR ──
        if strategy == "asr_first":
            query = messages[-1].get("content", "")
            # 去掉可能的前缀指令，保留纯台词
            for prefix in ["ASR匹配：", "asr匹配：", "匹配台词：", "ASR台词匹配："]:
                if query.startswith(prefix):
                    query = query[len(prefix):]
                    break
            results = self._asr_first_search(query, limit=5)
            reply = self._format_chat_reply(results, query)
            self._json({"reply": reply, "results": results, "action": "search"})
            return

        # Step 1: DeepSeek 意图理解 + query 精炼（语义搜索路径）
        intent = self._chat_intent(messages, context)
        action = intent.get("action", "search")
        reply = ""
        results = []

        if action == "search":
            query = intent.get("query", "")
            if not query:
                query = messages[-1].get("content", "") if messages else ""
            mode = intent.get("mode", "semantic")
            results = self._search(query, mode=mode, limit=5, eps=eps)
            reply = intent.get("reply", "") or self._format_chat_reply(results, query)
        elif action == "preview":
            ep = intent.get("ep", 1)
            t = intent.get("start", 0)
            sid = f"chat_{int(time.time())}"
            self._serve_preview(str(ep), float(t), sid)
            return
        else:
            reply = intent.get("reply", "我理解你想" + action + "，但这个功能还在开发中。你可以先试试搜索：直接描述你想找的画面。")
            results = self._search(messages[-1].get("content", ""), mode="semantic", limit=3)

        self._json({"reply": reply, "results": results, "action": action})

    def _chat_intent(self, messages, context, strategy=""):
        """DeepSeek 理解对话意图 → {action, query, reply, mode?, ep?, start?, end?}"""
        import urllib.request as _ur

        sid = context.get("sid", "?")
        seq = context.get("seq", "?")
        narration = context.get("narration", "")

        # ASR优先 vs 语义搜索的规则差异
        if strategy == "asr_first":
            mode_hint = (
                "当前匹配策略：ASR优先（台词匹配模式）\n"
                "规则：\n"
                "- 保持台词原文的关键词，不要转写为视觉描述\n"
                "- ASR匹配需要在剧中出现的原话，用剧中角色的真实台词\n"
                "- mode 固定为 \"asr_first\"\n"
                "- query 使用原台词中的关键词（10-30字）\n"
            )
        else:
            mode_hint = (
                "当前匹配策略：语义搜索（画面匹配模式）\n"
                "规则：\n"
                "- 用视觉关键词：表情（严肃/愤怒/微笑）、动作（拍桌/站起/低头）、场景（办公室/老宅/客厅）\n"
                "- mode 固定为 \"semantic\"\n"
                "- query 控制在 50 字内\n"
            )

        system_prompt = (
            "你是 VIBECAP 的 AI 剪辑助手，名字叫「小 V」。\n"
            "你正在帮助一位视频剪辑师，从电视剧《都挺好》的原剧素材中搜索匹配的镜头画面。\n\n"
            "你的风格：专业、热情、简洁。像一个熟悉这部剧的剪辑搭档。\n\n"
            f"当前工作上下文：解说段 S{sid}-{seq}\n"
            f"解说词内容：{narration[:200]}\n\n"
            + mode_hint + "\n"
            "你的任务：理解剪辑师的意图，输出 JSON。\n\n"
            "支持的 action:\n"
            '- "search": 剪辑师描述想要的画面 → 你精炼为搜索 query，附带 mode 字段\n'
            '- "chat": 闲聊、打招呼、问功能\n\n'
            '输出格式（严格 JSON）:\n'
            '{"action":"search", "query":"搜索词", "mode":"asr_first|semantic", "reply":"自然的回复"}\n'
            '{"action":"chat", "reply":"你的回复"}\n\n'
            "通用精炼规则：\n"
            "- 累积多轮对话中的条件，不要丢失之前的约束\n"
            "- 用户说'不要XX'→排除XX；'换XX'→替换条件\n"
            "- 用角色真名（苏大强、蒙总、苏明玉等），禁止用他/她\n"
            "- reply 要自然亲切，20 字内"
        )

        api_messages = [{"role": "system", "content": system_prompt}]
        for m in messages[-6:]:
            role = "assistant" if m.get("role") == "ai" else "user"
            api_messages.append({"role": role, "content": m.get("content", "")[:500]})
        api_messages.append({"role": "user", "content": "输出JSON："})

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": api_messages,
            "temperature": 0.7,
            "max_tokens": 400,
        }).encode("utf-8")

        try:
            req = _ur.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            with _ur.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            print(f"[chat_intent] LLM 失败: {e}")
            return {"action": "search", "query": messages[-1].get("content", "") if messages else "",
                    "reply": "让我帮你找找~"}

    def _format_chat_reply(self, results, query):
        """搜索结果简短回复"""
        if not results:
            return f'没找到匹配的镜头，换个角度描述试试？'
        return f'找到 {len(results)} 个匹配镜头，看看哪个合适~'

    def _generate_storyboard(self, narration, num=3):
        '''将解说词转写为1-3个视觉搜索描述，每个从不同角度匹配原剧镜头'''
        if not narration or not narration.strip():
            return []
        import urllib.request as _ur

        # 加载角色信息
        char_ctx = ""
        try:
            char_file = PROJECT_DIR / "characters.json"
            if char_file.exists():
                chars = json.load(open(char_file)).get("characters", {})
                parts = []
                for name, info in chars.items():
                    aliases = "/".join(info.get("static_names", []))
                    alt = "、".join(info.get("aliases", [])[:3])
                    parts.append(f"{name}（{aliases}）" + (f" 也称：{alt}" if alt else ""))
                if parts:
                    char_ctx = "已知角色：\n" + "\n".join(parts) + "\n\n"
        except Exception:
            pass

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        api_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [{
                "role": "system",
                "content": (
                    "你是视频搜索查询专家。你的任务是：把一段解说词转写为1-3个视觉搜索描述，"
                    "每个描述将用BGE语义搜索在原剧VLM素材库中检索匹配的镜头画面。\n\n"
                    "输出格式：每行一个，格式为「镜头N：视觉描述」\n\n"
                    "核心规则：\n"
                    "1. 【浓缩而非拆散】一句解说词通常只对应1-3个镜头。"
                    "每个镜头描述覆盖解说词的一个主要视觉角度，不要把一句话拆得支离破碎。\n"
                    "2. 【视觉风格翻译】把叙事文字翻译成VLM视觉描述风格的语言：用具体的人物动作、"
                    "面部表情、空间关系、光线氛围来描述，而不是复述剧情。\n"
                    "3. 【50-100字】每个描述要有足够细节让BGE做精准语义匹配，但不能冗长稀释信号。\n"
                    "4. 【用真名不用代词】使用角色真名（蒙总、蒙太、明玉、沈浩），禁止「他」「她」。\n"
                    "5. 【不同角度互补】如果有多个描述，每个聚焦不同人物或不同时刻，互补而非重复。\n"
                    "6. 【只转写不编造】基于解说词中真实发生的事来写，不要添加解说词没提到的画面。\n\n"
                    "参考示例：\n"
                    "解说词：「蒙总决定清理亲戚，遭到蒙太激烈反对，蒙太以离婚相要挟」\n"
                    "输出：\n"
                    "「镜头1：蒙总和蒙太在办公室激烈对峙，蒙太情绪激动手指蒙总，蒙总面色凝重眉头紧锁，气氛剑拔弩张」\n"
                    "「镜头2：蒙总独自坐在昏暗办公室，神情疲惫无奈，低头沉思，面对离婚威胁内心挣扎」"
                )
            }, {
                "role": "user",
                "content": f"{char_ctx}解说词：{narration}\n\n请转写为视觉搜索描述："
            }],
            "temperature": 0.6,
            "max_tokens": 1500,
        }).encode("utf-8")
        req = _ur.Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with _ur.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            lines = [l.strip() for l in text.strip().split("\n") if l.strip() and len(l.strip()) > 15]
            return lines[:num]
        except Exception as e:
            print(f"[storyboard_suggest] LLM call failed: {e}")
            return []

    # ── 策划台: 转写分析 ──
    def _handle_analyze_transcript(self):
        """POST /script/analyze_transcript — LLM 分析采访转写，标注金句+识别结构"""
        import urllib.request as _ur
        data = json.loads(self._read_body())
        transcript = data.get("transcript", "").strip()
        if not transcript:
            self._json({"ok": False, "error": "请提供转写文本"}, 400)
            return

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            self._json({"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}, 500)
            return

        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [{
                "role": "system",
                "content": (
                    "你是短视频口播剪辑策划助手。分析引导式采访转写，找到最有价值的内容。\n\n"
                    "素材特征：引导式聊天中有两层——内容层(正式讲述，可入正片)和元讨论层(商量怎么讲/自我评价/重述尝试，不入正片)。主持人的短问句和肯定词也不入正片。\n\n"
                    "标注每句：\n"
                    "  speaker: guest/host\n"
                    "  layer: content(正式讲述)/meta(元讨论)/guide(主持人引导)\n"
                    "  importance: 1-5 (5=金句hook, 4=核心观点/数据, 3=细节, 2=过渡, 1=冗余。meta/guide类默认-2)\n"
                    "  narrative_role: hook_tension(激将式)/hook_promise(价值承诺)/personal_reveal(个人揭示)/empathy(共情)/evidence(方法论)/bridge(过桥)/turn(反转)/proof(案例)/insight(洞见)\n"
                    "  is_golden: 适合做hook或收尾的标题级金句\n\n"
                    "识别：\n"
                    "  hook_candidates: 可重复锚定2-4次的核心金句列表\n"
                    "  opening_strategy: tension_first或promise_first\n"
                    "  empathy_moment: 共情句(如'爱学习但别乱学')或null\n"
                    "  exclusive_moment: 独家揭示句(如'从没对外分享过')或null\n\n"
                    "输出严格JSON(无markdown代码块):\n"
                    '{"sentences":[{"index":0,"text":"原文","start_sec":0,"end_sec":2,"speaker":"guest","layer":"content","importance":5,"narrative_role":"hook_tension","is_golden":true,"topic":"开场","redundancy":null}],"hook_candidates":[],"structure":{"title_suggestion":"标题","opening_strategy":"tension_first","hook_line":"核心金句","empathy_moment":null,"exclusive_moment":null,"outline":[{"label":"段落","narrative_role":"hook_tension","sentence_indices":[0]}]}}'
                )
            }, {
                "role": "user",
                "content": f"采访转写文本：\n{transcript}"
            }],
            "temperature": 0.3,
            "max_tokens": 8000,
        }).encode("utf-8")

        try:
            req = _ur.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            with _ur.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].split("```")[0].strip()
            # 修复常见 JSON 错误
            parsed = None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # 尝试修复截断的 JSON
                # 1. 移除末尾不完整的行
                lines = text.split("\n")
                for trim in range(1, min(20, len(lines))):
                    fixed = "\n".join(lines[:-trim])
                    if fixed.rstrip().endswith("}") or fixed.rstrip().endswith("]"):
                        try:
                            parsed = json.loads(fixed + ("}" if fixed.count("{") > fixed.count("}") else "") + ("]" if fixed.count("[") > fixed.count("]") else ""))
                            break
                        except json.JSONDecodeError:
                            continue
            if not parsed:
                self._json({"ok": False, "error": "AI 返回格式异常，请重试", "raw": text[:500]}, 500)
                return
            self._json({"ok": True, **parsed})
        except Exception as e:
            print(f"[analyze_transcript] failed: {e}")
            self._json({"ok": False, "error": str(e)[:200]}, 500)

    # ── 策划台: 主题+结构 → 文案生成 ──
    def _handle_generate_from_outline(self):
        """POST /script/generate_from_outline — 根据主题和结构大纲生成 segments"""
        import urllib.request as _ur
        data = json.loads(self._read_body())
        topic = data.get("topic", "").strip()
        outline = data.get("outline", [])  # [{label: "开场hook", narrative_role: "hook_tension"}]
        transcript = data.get("transcript", "").strip()

        if not topic or not outline:
            self._json({"ok": False, "error": "请提供 topic 和 outline"}, 400)
            return

        # 构建大纲描述
        outline_desc = "\n".join(f"{i+1}. [{o.get('narrative_role','?')}] {o.get('label','')}" for i, o in enumerate(outline))

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [{
                "role": "system",
                "content": (
                    "你是短视频口播剪辑的文案助手。根据剪辑师确定的主题和大纲，从采访转写中提取最合适的原话，生成 segments.json。\n\n"
                    "规则：\n"
                    "1. 每段 highlight_text 必须是转写中真实存在的原话（可做最小限度的去口头禅），不要自己编造\n"
                    "2. 每段标注 source_start / source_end（从转写时间戳中取）\n"
                    "3. 根据 narrative_role 选择合适的表达力度：\n"
                    "   hook_tension: 挑衅/激将式，短而有力（5-10字）\n"
                    "   hook_promise: 价值承诺式，一句话说清收益（10-20字）\n"
                    "   personal_reveal: 个人揭示，用\"我\"开头（10-20字）\n"
                    "   empathy: 共情，理解观众痛点（10-20字）\n"
                    "   evidence: 方法论/数据，具体可执行（15-40字）\n"
                    "   bridge: 情绪过桥，一句话（5-10字）\n"
                    "   turn: 反转，孤句成段（2-5字）\n"
                    "   proof: 亲身案例，数据支撑（15-30字）\n"
                    "   insight: 深层洞见（10-25字）\n"
                    "4. 每段 edit_type: 短句用trim, 多句合并用merge\n"
                    "5. topic 标签用于分段组织\n\n"
                    "输出严格JSON:\n"
                    '{"segments":[{"seg_id":0,"highlight_text":"原话","source_start":63.0,"source_end":67.0,"topic":"开场hook","edit_type":"trim","narration_text":"","note":"为什么选这句"}]}'
                )
            }, {
                "role": "user",
                "content": (
                    f"视频主题：{topic}\n\n"
                    f"结构大纲：\n{outline_desc}\n\n"
                    f"采访转写（带时间戳）：\n{transcript[:4000]}"
                )
            }],
            "temperature": 0.4,
            "max_tokens": 4000,
        }).encode("utf-8")

        try:
            req = _ur.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            with _ur.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].split("```")[0].strip()
            parsed = json.loads(text)
            self._json({"ok": True, "topic": topic, "segments": parsed.get("segments", [])})
        except Exception as e:
            print(f"[generate_from_outline] failed: {e}")
            self._json({"ok": False, "error": str(e)[:200]}, 500)

    # ── 三步文案生成 ──
    def _handle_generate_script(self):
        """POST /script/generate_script — 三步混编算法生成完整 segments"""
        import urllib.request as _ur
        data = json.loads(self._read_body())
        topic = data.get("topic", "").strip()
        if not topic:
            self._json({"ok": False, "error": "请提供视频主题"}, 400)
            return

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            self._json({"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}, 500)
            return

        # 加载分类数据
        classified = []
        cf = PROJECT_DIR / "sources_clean" / "classified_学习新东方.json"
        if cf.exists():
            classified = json.load(open(cf))
        content_only = [s for s in classified if s.get('layer') == 'content']
        content_text = '\n'.join(
            f"[{s['start_sec']:.0f}s|imp={s.get('importance',3)}] {s['text']}"
            for s in content_only
        )

        def _call_llm(system_prompt, user_content, temp=0.4, label="?"):
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": user_content}],
                "temperature": temp, "max_tokens": 3000,
            }).encode()
            for attempt in range(3):
                try:
                    req = _ur.Request(
                        "https://api.deepseek.com/v1/chat/completions",
                        data=payload,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                    )
                    with _ur.urlopen(req, timeout=180) as resp:
                        result = json.loads(resp.read())
                    text = result["choices"][0]["message"]["content"].strip()
                    if text.startswith("```"): text = text.split("\n", 1)[1].split("```")[0].strip()
                    return json.loads(text)
                except Exception as e:
                    print(f"  [{label}] attempt {attempt+1}/3 failed: {e}")
                    if attempt == 2: raise
                    time.sleep(3)
            return {}

        try:
            # ═══ Step 1: 大结构 ═══
            print("[gen_script] Step 1: 大结构")
            structure = _call_llm(  # Step 1
                "你是短视频策划导演。根据采访内容精华，设计一个60-90秒短视频的5-8段叙事结构。\n\n"
                "★ 硬约束: 各段duration之和必须≤100秒(预留10-20秒缓冲)。\n"
                "★ 每段duration根据内容重要性分配,核心方法论段可15-20秒,过渡段3-5秒。\n\n"
                "要求:\n"
                "1. 确定核心主题(≤15字)\n"
                "2. 每段标注: narrative_role + 核心论点(一句话) + 目标时长(秒)\n"
                "3. narrative_role: hook_tension/hook_promise/personal_reveal/empathy/evidence/bridge/turn/proof/insight\n"
                "4. 结构必须有起伏: 开头激将+个人揭示→方法论→反转→案例→洞察收尾\n"
                "5. 共情层放在方法论之前\n\n"
                "输出JSON: {\"topic\":\"主题\",\"sections\":[{\"role\":\"hook_tension\",\"point\":\"论点\",\"duration\":5}]}",
                f"视频主题方向: {topic}\n\n采访内容精华:\n{content_text[:4000]}"
            )
            total_budget = sum(s.get('duration', 0) for s in structure.get('sections', []))
            print(f"  → {structure.get('topic','?')}, {len(structure.get('sections',[]))} 段, 预算{total_budget}s")

            # ═══ Step 2: 组织语句（混编） ═══
            print("[gen_script] Step 2: 混编选句")
            all_selected = []
            total_src_dur = 0  # 源素材总时长
            for i, sec in enumerate(structure.get('sections', [])):
                result = _call_llm(
                    "你是短视频精编师。从完整采访ASR中为指定段落选出最合适的原话。\n\n"
                    "★ 硬约束: 选句总源时长控制在目标时长的1.3倍以内(留30%精剪余量)。\n"
                    "★ 60-90秒成片 ≈ 需要120-160秒源素材。\n\n"
                    "规则:\n"
                    "1. 跨时间选择（不按ASR顺序,按叙事逻辑）\n"
                    "2. 优先选 importance≥4 的句子\n"
                    "3. 同义句只选最精炼的一句\n"
                    "4. 选3-8句,总源时长控制在目标时长的80-130%\n"
                    "5. 选句需覆盖论点不同维度\n\n"
                    "输出JSON: {\"sentences\":[{\"text\":\"原话\",\"source_start\":63.0,\"source_end\":67.0,\"reason\":\"为何选\"}]}",
                    f"段落角色: {sec['role']}\n核心论点: {sec['point']}\n目标时长: ~{sec['duration']}s\n\n"
                    f"采访ASR:\n{content_text[:5000]}",
                    label=f"Step2-{i}"
                )
                sentences = result.get('sentences', [])
                sec_dur = sum(s.get('source_end', s.get('source_start',0)+3) - s.get('source_start',0) for s in sentences)
                total_src_dur += sec_dur
                for s in sentences:
                    s['topic'] = sec['point'][:20]
                    s['section_role'] = sec['role']
                all_selected.extend(sentences)
                print(f"  Section {i} ({sec['role']}): {len(sentences)}句, 源{sec_dur:.0f}s")
                time.sleep(0.3)

            # 合并+去重（同位置+同文本）
            seen = set()
            merged = []
            for s in all_selected:
                key = f"{s.get('source_start',0):.0f}_{s['text'][:20]}"
                if key not in seen:
                    seen.add(key)
                    merged.append(s)
            print(f"  合并去重: {len(all_selected)} → {len(merged)} 句")

            # ═══ Step 3: 精细化 ═══
            print("[gen_script] Step 3: 精细化")
            script_preview = '\n'.join(
                f"[{i}] [{s.get('section_role','?')}] {s['text'][:80]}"
                for i, s in enumerate(merged)
            )
            refinement = _call_llm(
                "你是短视频精编师。审核下面的脚本，完成三件事:\n\n"
                "1. 检查段落间是否有逻辑断裂，是否需要过渡句\n"
                "2. 检查是否有连续3句以上来自同一时间段（产生堆砌感）\n"
                "3. 在必要处补写过渡句(≤15字)，标注 source: 'ai_generated'\n"
                "   每段之间最多补1句，整片最多补3句\n\n"
                "输出JSON: {\"checks\":{\"logic_gaps\":[],\"rhythm_issues\":[]},"
                "\"bridges\":[{\"after_index\":2,\"text\":\"过渡句\",\"topic\":\"过渡\"}],"
                "\"notes\":\"其他建议\"}",
                f"脚本(按叙事顺序排列):\n{script_preview}",
                label="Step3"
            )

            # 组装最终 segments
            segments = []
            seg_id = 0
            bridges = refinement.get('bridges', [])
            bridge_map = {b['after_index']: b for b in bridges}

            for i, s in enumerate(merged):
                segments.append({
                    "seg_id": seg_id,
                    "highlight_text": s['text'],
                    "source_start": s.get('source_start', 0),
                    "source_end": s.get('source_end', s.get('source_start', 0) + 5),
                    "topic": s.get('topic', ''),
                    "section_role": s.get('section_role', ''),
                    "edit_type": "trim",
                    "narration_text": "",
                    "note": s.get('reason', ''),
                })
                seg_id += 1

                # 插入 AI 过渡句
                if i in bridge_map:
                    b = bridge_map[i]
                    segments.append({
                        "seg_id": seg_id,
                        "highlight_text": b['text'],
                        "source_start": 0, "source_end": 0,
                        "topic": b.get('topic', '过渡'),
                        "section_role": "bridge",
                        "edit_type": "ai_generated",
                        "narration_text": "",
                        "note": "⚠️ AI补写,需人工配音或从素材补充",
                    })
                    seg_id += 1

            # 计算时间估计
            src_total = sum(
                (s.get('source_end', s.get('source_start',0)+3) - s.get('source_start',0))
                for s in segments if s.get('edit_type') != 'ai_generated'
            )
            est_final = src_total * 0.5  # 精剪约保留50%

            result = {
                "ok": True,
                "topic": structure.get('topic', topic),
                "sections": structure.get('sections', []),
                "segments": segments,
                "checks": refinement.get('checks', {}),
                "bridges": bridges,
                "notes": refinement.get('notes', ''),
                "total": len(segments),
                "ai_generated_count": len(bridges),
                "time_estimate": {
                    "budget": total_budget,
                    "source_total": round(src_total, 1),
                    "estimated_final": round(est_final, 1),
                    "target": "60-90s",
                    "status": "ok" if 50 <= est_final <= 110 else ("over" if est_final > 110 else "under"),
                }
            }
            self._json(result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)[:200]}, 500)

    def _handle_generate_script_stream(self):
        """POST /script/generate_script_stream — SSE 流式 Agent 流水线"""
        data = json.loads(self._read_body())
        topic = data.get("topic", "").strip()
        if not topic:
            self._json({"ok": False, "error": "请提供视频主题"}, 400); return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        # 心跳: 每15s发送一次,防止连接超时
        import threading
        heartbeat_active = [True]
        def heartbeat():
            while heartbeat_active[0]:
                time.sleep(15)
                try: emit("heartbeat", {"ts": time.time()})
                except: break
        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            from script_agents import run_pipeline

            # 加载 ASR (动态发现 classified 文件)
            clean_dir = PROJECT_DIR / "sources_clean"
            classified_files = list(clean_dir.glob("classified_*.json"))
            classified = []
            if classified_files:
                classified = json.load(open(classified_files[0]))
            content = [s for s in classified if s.get('layer') == 'content']
            ctx = '\n'.join(f"[{s['start_sec']:.0f}s|{s.get('importance',3)}] {s['text']}" for s in content)

            # 运行 Agent 流水线
            result = run_pipeline(topic, ctx, emit_progress=lambda step, msg, data=None:
                emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})}))

            if result.get('segments') and len(result['segments']) > 0:
                # ── 保存文案脚本到文件 ──
                tasks_dir = PROJECT_DIR / "tasks"
                tasks_dir.mkdir(parents=True, exist_ok=True)
                script_file = tasks_dir / "文案脚本.json"
                save_data = {
                    "topic": result.get("topic", topic),
                    "sections": result.get("sections", []),
                    "segments": result["segments"],
                    "total": result.get("total", len(result["segments"])),
                    "time_estimate": result.get("time_estimate", {}),
                    "review_issues": result.get("review_issues", []),
                    "review_verdict": result.get("review_verdict", "?"),
                }
                json.dump(save_data, open(script_file, "w"), ensure_ascii=False, indent=2)
                result["script_file"] = str(script_file)
                result["script_file_url"] = f"/tasks/文案脚本.json"
                print(f"[pipeline] 文案脚本已保存: {script_file}")

                emit("complete", result)
            else:
                emit("error", {"error": result.get('error', '生成失败: 未产出有效文案'), "detail": str(result.get('edit_notes',''))[:200]})
            time.sleep(0.5)  # 确保 complete 事件被客户端收到
            heartbeat_active[0] = False
        except Exception as e:
            import traceback; traceback.print_exc()
            try: emit("error", {"error": str(e)[:200]})
            except: pass
            heartbeat_active[0] = False

    def _handle_generate_story_first(self):
        """POST /script/generate_story_first — v4 故事优先流水线 (口播采访专用)"""
        data = json.loads(self._read_body())
        topic = data.get("topic", "").strip()
        if not topic:
            self._json({"ok": False, "error": "请提供视频主题"}, 400); return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        import threading
        heartbeat_active = [True]
        def heartbeat():
            while heartbeat_active[0]:
                time.sleep(15)
                try: emit("heartbeat", {"ts": time.time()})
                except: break
        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            from script_agents import story_first_pipeline

            # 加载完整 ASR (优先使用 enhanced 数据)
            clean_dir = PROJECT_DIR / "sources_clean"
            enhanced_file = clean_dir / "classified_enhanced.json"
            if enhanced_file.exists():
                enhanced = json.load(open(enhanced_file))
                # 用 guest content, 保留 original_text
                content = [s for s in enhanced
                          if s.get('speaker') == 'guest'
                          and s.get('layer') in ('content', 'guide')]
                ctx = '\n'.join(
                    f"[{s['start_sec']:.0f}s|{s.get('importance',3)}] {s.get('text', s.get('cleaned_text',''))}"
                    for s in content
                )
                emit("progress", {"step": "story", "status": "running",
                     "msg": f"📖 故事师: 加载{len(content)}句guest ASR (enhanced)..."})
            else:
                classified_files = list(clean_dir.glob("classified_*.json"))
                classified = json.load(open(classified_files[0])) if classified_files else []
                content = [s for s in classified if s.get('layer') == 'content']
                ctx = '\n'.join(
                    f"[{s['start_sec']:.0f}s|{s.get('importance',3)}] {s['text']}"
                    for s in content
                )
                emit("progress", {"step": "story", "status": "running",
                     "msg": f"📖 故事师: 加载{len(content)}句ASR..."})

            # 运行 v4 流水线 (单次 LLM 调用)
            result = story_first_pipeline(topic, ctx, emit_progress=lambda step, msg, data=None:
                emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})}))

            if result.get('segments') and len(result['segments']) > 0:
                # ── 保存到文件 ──
                tasks_dir = PROJECT_DIR / "tasks"
                tasks_dir.mkdir(parents=True, exist_ok=True)
                script_file = tasks_dir / "文案脚本.json"
                save_data = {
                    "topic": topic,
                    "story": result.get("story", ""),
                    "pipeline": "story-first-v4",
                    "segments": result["segments"],
                    "total": result.get("total", len(result["segments"])),
                    "time_estimate": result.get("time_estimate", {}),
                }
                json.dump(save_data, open(script_file, "w"), ensure_ascii=False, indent=2)
                result["script_file"] = str(script_file)
                result["script_file_url"] = f"/tasks/文案脚本.json"

                # ── v0.11: 同步写入 SQLite ──
                try:
                    drama_id = db.get_drama_id(_project_name)
                    if drama_id:
                        task_name = _args.task or f"story_{int(time.time())}"
                        # 查找或创建 task
                        existing = db.get_task(drama_id, task_name)
                        if existing:
                            task_id = existing["id"]
                            db.save_task_segments(task_id, result["segments"])
                        else:
                            task_id = db.create_task(drama_id, task_name)
                            db.save_task_segments(task_id, result["segments"])
                        print(f"[story-first] DB: task={task_name} task_id={task_id} segs={len(result['segments'])}")
                        result["task_id"] = task_id
                except Exception as e:
                    print(f"[story-first] DB save failed (non-critical): {e}")

                emit("complete", result)
            else:
                emit("error", {"error": result.get('error', '生成失败')})
            time.sleep(0.5)
            heartbeat_active[0] = False
        except Exception as e:
            import traceback; traceback.print_exc()
            try: emit("error", {"error": str(e)[:200]})
            except: pass
            heartbeat_active[0] = False

    def _resolve_sources_dir(self):
        """根据 ?project= 参数动态解析 sources 目录"""
        params = parse_qs(urlparse(self.path).query)
        proj = params.get("project", [_project_name])[0]
        return BASE_DIR / proj / "sources"

    def _handle_asr_raw(self):
        """GET /asr/raw — 返回项目所有 ASR 转写文本"""
        src_dir = self._resolve_sources_dir()
        lines = []
        for f in sorted(src_dir.glob("asr_*.json")) if src_dir.exists() else []:
            for s in json.load(open(f)):
                text = s.get("text", "").strip()
                if len(text) > 1:
                    lines.append(f"[{s.get('start', s.get('start_sec', 0)):.1f}s] {text}")
        self._json({"ok": True, "transcript": "\n".join(lines), "lines": len(lines)})

    def _handle_asr_classified(self):
        """GET /asr/classified — 返回 LLM 分类后的 ASR"""
        params = parse_qs(urlparse(self.path).query)
        proj = params.get("project", [_project_name])[0]
        src_dir = BASE_DIR / proj / "sources"
        clean_dir = BASE_DIR / proj / "sources_clean"

        # 优先读 sources_clean, 回退到 sources
        classified_files = list(clean_dir.glob("classified_*.json"))
        if not classified_files:
            classified_files = list(src_dir.glob("asr_*_classified.json"))
        if not classified_files:
            self._json({"ok": False, "error": f"未找到分类数据 ({proj})"}, 404)
            return

        data = json.load(open(classified_files[0]))
        stats = {}
        for s in data: stats[s.get('layer','?')] = stats.get(s.get('layer','?'), 0) + 1
        self._json({"ok": True, "segments": data, "stats": stats})

    def _serve_clip(self, req_task=None):
        # 从 URL query 或参数获取任务名
        params = parse_qs(urlparse(self.path).query)
        task_name = req_task or params.get("task", [None])[0] or _args.task
        task_dir = self._resolve_task_dir(task_name)
        clean = urlparse(self.path).path
        clean = unquote(clean.lstrip("/"))
        # 去掉 ?task= 之后的 query string（如果路径中意外包含）
        if "?" in clean:
            clean = clean.split("?")[0]
        if "tts_segments/" in clean:
            path = task_dir / "work_dir" / clean
        elif "export_clips/" in clean:
            path = task_dir / clean
        else:
            clean = clean.replace("clips/", "素材clips/")
            path = task_dir / clean
        if not path.exists(): return self.send_error(404)
        size = path.stat().st_size
        rh = self.headers.get("Range")
        if rh:
            start,end = 0,size-1
            m = rh.replace("bytes=","").split("-")
            start=int(m[0]) if m[0] else 0
            end=int(m[1]) if len(m)>1 and m[1] else size-1
            self.send_response(206)
            self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
            length=end-start+1
        else:
            start,end,length=0,size-1,size
            self.send_response(200)
        ct = "image/jpeg" if path.suffix in (".jpg",".jpeg") else ("image/png" if path.suffix==".png" else ("audio/wav" if path.suffix==".wav" else "video/mp4"))
        self.send_header("Content-Type",ct)
        self.send_header("Accept-Ranges","bytes")
        self.send_header("Content-Length",str(length))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        with open(path,"rb") as f:
            f.seek(start)
            while length>0:
                chunk=f.read(min(65536,length))
                if not chunk: break
                self.wfile.write(chunk)
                length-=len(chunk)

    def _serve_frontend(self, path):
        """Serve 前端生产构建 (SPA)。返回 True 表示已处理。"""
        if not FRONTEND_DIR.exists():
            return False
        clean = path.lstrip("/")
        # API 路由不走这里
        api_routes = {"/search", "/chat", "/segments.json", "/preview_video", "/status",
                       "/dramas", "/tasks", "/assign", "/copy", "/thumb", "/storyboard_suggest"}
        if path in api_routes:
            return False
        # 排除 API 前缀
        for prefix in ("/clips/", "/素材clips/", "/tts_segments/", "/posters/", "/proxies/", "/export_clips/"):
            if path.startswith(prefix):
                return False
        # 静态资源：直接 serve
        file_path = FRONTEND_DIR / clean if clean else FRONTEND_DIR / "index.html"
        if file_path.exists() and file_path.is_file():
            ext = file_path.suffix.lower()
            mime_map = {
                ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                ".json": "application/json", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml",
                ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
            }
            self._send_file(file_path, mime_map.get(ext, "application/octet-stream"))
            return True
        # SPA fallback: 非文件路径 → 返回 index.html
        if "." not in clean.split("/")[-1]:
            index_html = FRONTEND_DIR / "index.html"
            if index_html.exists():
                self._send_file(index_html, "text/html")
                return True
        return False

    def _serve_static(self, req_task=None):
        """静态文件 fallback：动态解析 ?task= 参数，从对应任务目录 serve 文件"""
        task_name = req_task or _args.task
        task_dir = self._resolve_task_dir(task_name)
        clean = urlparse(self.path).path
        clean = unquote(clean.lstrip("/"))
        if "?" in clean:
            clean = clean.split("?")[0]
        file_path = task_dir / clean
        if not file_path.exists() or not file_path.is_file():
            return self.send_error(404)
        ext = file_path.suffix.lower()
        mime_map = {
            ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
            ".json": "application/json", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4",
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        mime = mime_map.get(ext, "application/octet-stream")
        self._send_file(file_path, mime)

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(json.dumps(data,ensure_ascii=False).encode())

    def _read_body(self):
        if self._cached_body is None:
            self._cached_body = self.rfile.read(int(self.headers.get("Content-Length",0))).decode()
        return self._cached_body

# ── 编码 (BGE-large-zh-v1.5, 1024维) ──
_enc_model = None
def _encode(text):
    global _enc_model
    if _enc_model is None:
        from sentence_transformers import SentenceTransformer
        _enc_model = SentenceTransformer("BAAI/bge-base-zh-v1.5")
        # BGE 模型建议对 query 加前缀来提升效果
    return _enc_model.encode([text], normalize_embeddings=True)[0]

# ── 启动 ──
if __name__ == "__main__":
    port = _args.port
    print(f"VIBECAP 后端: project={_project_name} (type={_project_type})  task={_args.task}")
    print(f"  索引: {INDEX_FILE} ({'✓' if INDEX_FILE.exists() else '✗'})")
    print(f"  源视频: {sum(1 for v in SOURCE_VIDEOS.values() if v.exists())}/{len(SOURCE_VIDEOS)} 集")
    print(f"  监听: http://localhost:{port}/")
    ThreadingServer(("0.0.0.0", port), Handler).serve_forever()
