#!/usr/bin/env python3
"""素材搜索服务 v2: HuggingFace语义搜索 + 关键词兜底"""
import json, re, subprocess, pickle, time, threading, os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse, parse_qs
import numpy as np

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

# ── CLI 参数 ──
import argparse as _argparse
_parser = _argparse.ArgumentParser(description="VIBECAP 后端服务")
_parser.add_argument("--drama", default=os.environ.get("VIBECAP_DRAMA", "都挺好"), help="电视剧名")
_parser.add_argument("--task", default=os.environ.get("VIBECAP_TASK", "Task7024"), help="任务名")
_parser.add_argument("--port", type=int, default=8765, help="端口")
_args = _parser.parse_args()

BASE_DIR    = Path("/Users/zgl/VIBECAP")
DRAMA_DIR   = BASE_DIR / _args.drama
TASK_DIR    = DRAMA_DIR / "tasks" / _args.task
SOURCES_DIR = DRAMA_DIR / "sources"
WORK_DIR    = TASK_DIR / "work_dir"
CLIP_DIR    = TASK_DIR / "素材clips"
INDEX_FILE  = DRAMA_DIR / "semantic_index.pkl"

CLIP_DIR.mkdir(exist_ok=True)
WORK_DIR.mkdir(exist_ok=True)

VIDEO_DIR = Path("/Users/zgl/解说剪辑/都挺好原剧")
SOURCE_VIDEOS = {}
for ep in range(1, 47):  # EP1-46
    p = VIDEO_DIR / f"都挺好 {ep:02d}_1080p.mp4"
    if p.exists():
        SOURCE_VIDEOS[f"ep{ep}"] = p

class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

# ── 加载数据 ──
semantic_index = None
si_path = INDEX_FILE
if si_path.exists():
    semantic_index = pickle.load(open(si_path, "rb"))
    print(f"[search] 语义索引: {semantic_index['embeddings'].shape[0]} 条")

# 动态发现可用集数（ASR/VLM 数据 + 源视频）
AVAILABLE_EPS = sorted(set(
    int(d.name[2:]) for d in SOURCES_DIR.iterdir()
    if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
    and ((d / "asr_result.json").exists() or (d / "vlm_analysis.json").exists())
))
print(f"[search] 可用集数: {AVAILABLE_EPS}")

vlm_data = []
for ep in AVAILABLE_EPS:
    p = SOURCES_DIR / f"ep{ep}" / "vlm_analysis.json"
    if p.exists():
        for s in json.load(open(p)): s["_ep"]=ep; vlm_data.append(s)
print(f"[search] VLM 数据: {len(vlm_data)} 条")

asr_data = {}
for ep in AVAILABLE_EPS:
    p = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
    if p.exists():
        raw = json.load(open(p))
        # ASR 文本统一转简体，确保与搜索 query 的字符集一致
        for a in raw:
            a["text"] = _norm(a["text"])
        asr_data[ep] = raw
print(f"[search] ASR 数据: {sum(len(v) for v in asr_data.values())} 条, 覆盖 EP {sorted(asr_data.keys())}")

# ── Handler ──
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._cached_body = None  # 必须在 super().__init__ 之前，因为父类 __init__ 会触发 handle()
        super().__init__(*args, directory=str(TASK_DIR), **kwargs)

    def _resolve_task_dir(self, task_name=None):
        """解析任务目录：优先 ?task= 参数，否则用启动默认"""
        name = task_name or _args.task
        return DRAMA_DIR / "tasks" / name

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
        elif path == "/segments.json":
            task = req_task or _args.task
            seg_file = self._resolve_task_dir(task) / "segments.json"
            if seg_file.exists():
                self._json(json.load(open(seg_file)))
            else:
                self._json({"segments": [], "total_segments": 0})
        elif path == "/preview_video":
            task = req_task or _args.task
            self._serve_preview(params.get("ep",["1"])[0], float(params.get("t",["0"])[0]),
                               params.get("sid",["default"])[0], task=task)
        elif path == "/status":
            task = req_task or _args.task
            self._json({"ok": True, "drama": _args.drama, "task": task})
        elif path == "/dramas":
            self._json(self._list_dramas())
        elif path == "/tasks":
            drama = params.get("drama", [_args.drama])[0]
            self._json(self._list_tasks(drama))
        elif "/posters/" in path:
            self._serve_poster(path)
        elif "/素材clips/" in path or "/clips/" in path or "/tts_segments/" in path:
            self._serve_clip(req_task)
        else:
            # 静态文件 fallback：根据 ?task= 动态解析目录
            self._serve_static(req_task)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        req_task = params.get("task", [None])[0] or _args.task

        if path == "/chat":
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
        elif path == "/storyboard_suggest":
            data = json.loads(self._read_body())
            suggestions = self._generate_storyboard(data.get("narration", ""))
            self._json({"suggestions": suggestions})
        elif path == "/tasks/create":
            self._create_task()
        elif path == "/status":
            task_dir = self._resolve_task_dir(req_task)
            tasks = json.load(open(task_dir/"tasks.json")) if (task_dir/"tasks.json").exists() else []
            self._json({"pending":sum(1 for t in tasks if t.get("status")=="pending"), "done":sum(1 for t in tasks if t.get("status")=="done"), "total":len(tasks)})
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _search(self, query, limit=10, mode="hybrid"):
        if not query: return []
        if mode == "keyword":
            return self._keyword_search(query, limit)
        elif mode == "semantic":
            return self._semantic_search(query, limit)
        elif mode == "hybrid":
            return self._hybrid_search(query, limit)
        elif mode == "deep":
            return self._deep_search(query, limit)
        elif mode == "asr_first":
            return self._asr_first_search(query, limit)
        return self._hybrid_search(query, limit)

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
        if not semantic_index: return []
        emb = semantic_index["embeddings"]
        metas = semantic_index["metas"]
        q_emb = _encode(query)
        # BGE 已做 L2 normalize，点积 = 余弦相似度
        scores = np.dot(emb, q_emb)
        top = np.argsort(scores)[-30:][::-1]
        results = {}
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
        import urllib.request
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
        req = urllib.request.Request(
            f"{api_url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return [l.strip().lstrip("- 123456789.）)") for l in text.strip().split("\n") if l.strip()][:3]
        except Exception as e:
            print(f"[expand_query] failed: {e}")
            return []

    def _llm_rerank(self, query, candidates, top_n=10):
        '''LLM 对候选画面重排序'''
        import urllib.request
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
        req = urllib.request.Request(
            f"{api_url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
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

    def _serve_preview(self, ep, t, sid="default", task=None):
        task_name = task or _args.task
        clip_dir = self._resolve_clip_dir(task_name)
        src = SOURCE_VIDEOS.get(f"ep{ep}")
        if not src: return self.send_error(404)
        tmp = clip_dir / f"_pv_{sid}.mp4"
        clip_start = max(0, t - 2)
        clip_end = clip_start + 20
        subprocess.run(["ffmpeg","-y","-ss",str(clip_start),"-i",str(src),
            "-t","20","-vf","scale=640:360","-c:v","libx264","-preset","ultrafast",
            "-crf","28","-c:a","aac","-b:a","64k",str(tmp)], capture_output=True)
        if tmp.exists():
            # URL 带上 task 参数，确保前端后续请求路由到正确任务
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

        drama_name = data.get("drama", _args.drama)
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
        """列出所有电视剧"""
        dramas = []
        for d in BASE_DIR.iterdir():
            if d.is_dir() and (d / "tasks").exists() and (d / "semantic_index.pkl").exists():
                tasks_dir = d / "tasks"
                task_list = [t.name for t in tasks_dir.iterdir() if t.is_dir() and (t / "segments.json").exists()]
                dramas.append({"name": d.name, "tasks": len(task_list)})
        return sorted(dramas, key=lambda x: x["name"])

    def _list_tasks(self, drama):
        """列出电视剧的所有任务（含状态）"""
        drama_dir = BASE_DIR / drama
        tasks_dir = drama_dir / "tasks"
        if not tasks_dir.exists():
            return []
        tasks = []
        for t in tasks_dir.iterdir():
            if not t.is_dir() or t.name.startswith('.'):
                continue
            seg_file = t / "segments.json"
            if not seg_file.exists():
                continue
            try:
                segs = json.load(open(seg_file))
                task = {
                    "name": t.name,
                    "segments": segs.get("total_segments", 0),
                    "status": "editing",
                    "duration": 0
                }
                # 读取状态
                status_file = t / "status.json"
                if status_file.exists():
                    task["status"] = json.load(open(status_file)).get("status", "editing")
                # 读取时长
                narr_file = t / "work_dir" / "narration.json"
                if narr_file.exists():
                    narr = json.load(open(narr_file))
                    task["duration"] = round(sum(s.get("duration", s.get("end", 0) - s.get("start", 0)) for s in narr), 1)
                tasks.append(task)
            except Exception:
                tasks.append({"name": t.name, "segments": 0, "status": "editing", "duration": 0})
        return sorted(tasks, key=lambda x: x["name"])

    # ── AI 聊天搜索 ──

    def _handle_chat(self):
        """POST /chat — 对话式素材搜索"""
        data = json.loads(self._read_body())
        messages = data.get("messages", [])
        context = data.get("context", {})

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
            results = self._search(query, mode=mode, limit=5)
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
        import urllib.request

        # 加载角色信息
        char_ctx = ""
        try:
            char_file = DRAMA_DIR / "characters.json"
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
        req = urllib.request.Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            lines = [l.strip() for l in text.strip().split("\n") if l.strip() and len(l.strip()) > 15]
            return lines[:num]
        except Exception as e:
            print(f"[storyboard_suggest] LLM call failed: {e}")
            return []

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
        ct = "image/jpeg" if path.suffix in (".jpg",".jpeg") else ("image/png" if path.suffix==".png" else "video/mp4")
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
    print(f"VIBECAP 后端: drama={_args.drama}  task={_args.task}")
    print(f"  索引: {INDEX_FILE} ({'✓' if INDEX_FILE.exists() else '✗'})")
    print(f"  源视频: {sum(1 for v in SOURCE_VIDEOS.values() if v.exists())}/{len(SOURCE_VIDEOS)} 集")
    print(f"  监听: http://localhost:{port}/")
    ThreadingServer(("0.0.0.0", port), Handler).serve_forever()
