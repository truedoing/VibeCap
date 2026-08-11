"""VibeCut Server v1.2 — FastAPI 主入口

drama编剧Agent + interview编剧台 + 导演Agent分镜匹配
"""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs
from typing import Optional
from contextlib import asynccontextmanager
from pydantic import BaseModel

import numpy as np
from fastapi import FastAPI, Request, Query, UploadFile, File, Form, HTTPException
from fastapi.responses import (
    JSONResponse, StreamingResponse, FileResponse, Response, PlainTextResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ── 本地模块 ──
from config import (
    project_name, project_type, PROJECT_DIR, BASE_DIR, SERVER_DIR,
    FRONTEND_DIR, PYTHON_BIN,
    SOURCES_DIR, PROXY_DIR, PROXY_MANIFEST, CLEAN_DIR,
    INDEX_NPY, INDEX_META, INDEX_FILE,
    SOURCE_VIDEOS, args,
    resolve_task_dir, resolve_clip_dir, resolve_work_dir,
)
from db import VibeCutDB
from lib.env import load_env
from lib.embeddings import get_model as get_bge_model, encode as bge_encode

# ── 环境变量 ──
load_env()
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ── 数据库 ──
DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


# ═══════════════════════════════════════════════════════════════
# 生命周期：索引加载 + Agent 搜索注入
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时加载索引和 BGE 模型"""
    global semantic_emb, semantic_metas, vlm_data, asr_data, interview_asr, available_eps

    print(f"[init] project={project_name} (type={project_type})")

    # ── 初始化 VLM 缓存 ──
    from lib.vlm_cache import set_project_dir
    set_project_dir(PROJECT_DIR)

    # ── 加载语义索引 ──
    if project_type == "drama":
        if INDEX_NPY.exists() and INDEX_META.exists():
            semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
            semantic_metas = json.load(open(INDEX_META))
            print(f"[search] 语义索引 (mmap): {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")
        elif INDEX_FILE.exists():
            import pickle
            index = pickle.load(open(INDEX_FILE, "rb"))
            semantic_emb = np.array(index["embeddings"])
            semantic_metas = index["metas"]
            print(f"[search] 语义索引 (pkl): {semantic_emb.shape[0]} 条")
    else:
        if INDEX_NPY.exists() and INDEX_META.exists():
            semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
            semantic_metas = json.load(open(INDEX_META))
            print(f"[search] 语义索引 (mmap): {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")

    # ── 加载 ASR + VLM 数据 ──
    if project_type == "drama":
        import pickle as _pk
        for ep in range(1, 47):
            ep_str = f"{ep:02d}"
            # ASR — 优先从 ep{N}/asr_result.json 加载，兼容旧路径
            asr_file = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"ep{ep_str}" / "asr_result.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"asr_ep{ep_str}.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"asr_{ep_str}.json"
            if asr_file.exists():
                asr_data[ep] = json.load(open(asr_file))
                available_eps.append(ep)

            # VLM
            vlm_file = SOURCES_DIR / f"vlm_ep{ep_str}.json"
            if not vlm_file.exists():
                vlm_file = SOURCES_DIR / f"vlm_ep{ep_str}_scene.json"
            if vlm_file.exists():
                vlm_list = json.load(open(vlm_file))
                for s in vlm_list:
                    s["_ep"] = ep
                vlm_data.extend(vlm_list)

        print(f"[data] 加载: {len(asr_data)} 集 ASR, {len(vlm_data)} 条 VLM")
    elif project_type == "interview":
        # 加载分类后的 ASR
        for cf in sorted(CLEAN_DIR.glob("classified_*.json")):
            if cf.name != "classified_enhanced.json":
                interview_asr = json.load(open(cf))
                print(f"[data] 口播 ASR: {cf.name} ({len(interview_asr)} 句)")
                break

    # ── 注入 Agent 搜索 ──
    try:
        from script_agents import set_search_fn

        def _agent_search(query, limit=15):
            if semantic_emb is None:
                return []
            q_emb = bge_encode(query)
            scores = np.dot(semantic_emb, q_emb)
            top = np.argsort(scores)[-limit * 2:][::-1]
            results = []
            for i in top:
                if scores[i] <= 0.25:
                    continue
                m = semantic_metas[i]
                display_text = m.get("original_text", m.get("text", ""))
                results.append({
                    "start": m.get("start", 0),
                    "end": m.get("end", m.get("start", 0) + 4),
                    "description": display_text[:200],
                    "asr": display_text[:200],
                    "cleaned_text": m.get("text", "")[:200],
                    "score": round(float(scores[i]) * 100, 1),
                })
            return sorted(results, key=lambda x: -x["score"])[:limit]

        set_search_fn(_agent_search)

        # 预热 BGE 模型
        print("[agent] 预热 BGE 模型...")
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
        if not warm_ready.wait(timeout=30):
            print("[agent] ⚠️ 预热超时(30s)")
    except Exception as e:
        print(f"[agent] search injection failed: {e}")

    # 注入 handlers 所需的全局搜索状态
    import handlers.search as hs
    hs.semantic_emb = semantic_emb
    hs.semantic_metas = semantic_metas
    hs.asr_data = asr_data
    hs.vlm_data = vlm_data
    hs.interview_asr = interview_asr

    print(f"[init] 就绪 — http://0.0.0.0:{args.port}/")
    yield  # 应用运行中
    print("[init] 关闭")


# ── 全局搜索状态 ──
semantic_emb = None
semantic_metas = None
vlm_data = []
asr_data = {}
interview_asr = None
available_eps = []

# ── FastAPI App ──
app = FastAPI(title="VibeCut API", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _read_json_body(request: Request) -> dict:
    """同步读取 JSON body（FastAPI 也能用 request.json()，但在依赖中需要异步）"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在事件循环中，用同步方式
            import warnings
            body = request._body
            if body is None:
                return {}
            return json.loads(body)
        return {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
# GET 端点
# ═══════════════════════════════════════════════════════════════

@app.get("/status")
def health_check():
    return {
        "status": "ok",
        "project": project_name,
        "type": project_type,
        "task": args.task,
        "version": "1.1.0",
    }


@app.get("/search")
def api_search(
    q: str = Query(""),
    mode: str = Query("hybrid"),
    limit: int = Query(10),
    eps: str = Query(None),
):
    from handlers.search import search
    return search(q, limit=limit, mode=mode, eps=eps)


@app.get("/dramas")
def api_list_dramas():
    from handlers.tasks import list_dramas
    return list_dramas()


@app.get("/tasks")
def api_list_tasks(drama: str = Query(None)):
    drama_name = drama or project_name
    from handlers.tasks import list_tasks
    return list_tasks(drama_name)


@app.get("/segments.json")
def api_segments(task: str = Query(None)):
    """任务分段 (DB→文件fallback)"""
    task_name = task or args.task
    drama_id = db.get_drama_id(project_name)
    if drama_id:
        task_obj = db.get_task(drama_id, task_name)
        if task_obj:
            segments = db.get_task_segments(task_obj["id"])
            if segments and len(segments) > 0:
                result = {"segments": segments, "total_segments": len(segments),
                          "project_type": project_type}
                located_file = resolve_task_dir(task_name) / "segments_located.json"
                if located_file.exists():
                    try:
                        located = json.load(open(located_file))
                        located_map = {s.get("seg_id"): s for s in located.get("segments", [])}
                        for seg in result["segments"]:
                            lid = seg.get("seg_id")
                            if lid is not None and lid in located_map:
                                loc = located_map[lid]
                                seg["video_start"] = loc.get("video_start")
                                seg["video_end"] = loc.get("video_end")
                                seg["ep"] = loc.get("ep")
                    except Exception:
                        pass
                return JSONResponse(result)

    # Fallback: 文件系统
    seg_file = resolve_task_dir(task_name) / "segments.json"
    if seg_file.exists():
        data = json.load(open(seg_file))
        data["project_type"] = project_type
        return JSONResponse(data)

    # 项目级兜底
    project_seg = PROJECT_DIR / "tasks" / "segments.json"
    if project_seg.exists():
        return JSONResponse({"segments": json.load(open(project_seg)).get("segments", [])})

    return JSONResponse({}, status_code=404)


@app.get("/narration.json")
def api_narration(task: str = Query(None)):
    task_name = task or args.task
    narr_file = resolve_work_dir(task_name) / "narration.json"
    if narr_file.exists():
        raw = json.load(open(narr_file))
        if isinstance(raw, list):
            wrapped = [{"index": s.get("index", i), "start": s["start"], "end": s["end"],
                        "narration": s.get("narration", ""),
                        "pause_after_ms": s.get("pause_after_ms", 0),
                        "overlaps_speech": s.get("overlaps_speech", False),
                        "emotion": s.get("emotion", "")}
                       for i, s in enumerate(raw)]
            return JSONResponse({"segments": wrapped})
        return JSONResponse(raw)
    return JSONResponse({}, status_code=404)


@app.get("/tasks/文案脚本.json")
def api_script_file(task: str = Query(None)):
    task_name = task or args.task
    script_file = resolve_task_dir(task_name) / "文案脚本.json"
    if not script_file.exists():
        script_file = PROJECT_DIR / "tasks" / "文案脚本.json"
    if script_file.exists():
        return JSONResponse(json.load(open(script_file)))
    return JSONResponse({"ok": False, "error": "文案脚本尚未生成"}, status_code=404)


@app.get("/asr/raw")
def api_asr_raw(project: str = Query(None)):
    proj = project or project_name
    src_dir = BASE_DIR / proj / "sources"
    lines = []
    for f in sorted(src_dir.glob("asr_*.json")) if src_dir.exists() else []:
        for s in json.load(open(f)):
            text = s.get("text", "").strip()
            if len(text) > 1:
                lines.append(f"[{s.get('start', s.get('start_sec', 0)):.1f}s] {text}")
    return {"ok": True, "transcript": "\n".join(lines), "lines": len(lines)}


@app.get("/asr/classified")
def api_asr_classified(project: str = Query(None)):
    proj = project or project_name
    src_dir = BASE_DIR / proj / "sources"
    clean_dir = BASE_DIR / proj / "sources_clean"
    classified_files = list(clean_dir.glob("classified_*.json"))
    if not classified_files:
        classified_files = list(src_dir.glob("asr_*_classified.json"))
    if not classified_files:
        return JSONResponse({"ok": False, "error": f"未找到分类数据 ({proj})"}, status_code=404)
    data = json.load(open(classified_files[0]))
    stats = {}
    for s in data:
        stats[s.get('layer', '?')] = stats.get(s.get('layer', '?'), 0) + 1
    return {"ok": True, "segments": data, "stats": stats}


@app.get("/proxies/manifest")
def api_proxy_manifest():
    from handlers.media import get_proxy_manifest
    return get_proxy_manifest()


@app.get("/proxies/{filename:path}")
def api_serve_proxy(filename: str, request: Request):
    """代理视频文件 + HTTP Range"""
    file_path = PROXY_DIR / filename.split("/")[-1]
    if not file_path.exists():
        raise HTTPException(404)

    size = file_path.stat().st_size
    range_header = request.headers.get("Range")

    if range_header:
        start, end = 0, size - 1
        m = range_header.replace("bytes=", "").split("-")
        start = int(m[0]) if m[0] else 0
        end = int(m[1]) if len(m) > 1 and m[1] else size - 1
        length = end - start + 1

        def ranged_file():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        return StreamingResponse(
            ranged_file(), status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(length),
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=86400",
            },
        )
    else:
        return FileResponse(file_path, media_type="video/mp4",
                            headers={"Accept-Ranges": "bytes",
                                     "Cache-Control": "public, max-age=86400"})


@app.get("/clips/{file_path:path}")
def api_serve_clip(file_path: str, task: str = Query(None)):
    """任务目录 clip 文件 + Range"""
    task_name = task or args.task
    from handlers.media import serve_task_file
    path, mime = serve_task_file(task_name, f"/clips/{file_path}")
    if not path:
        raise HTTPException(404)

    from fastapi.responses import FileResponse as FR
    return FR(path, media_type=mime,
              headers={"Accept-Ranges": "bytes", "Access-Control-Allow-Origin": "*"})


@app.get("/export_clips/{file_path:path}")
def api_serve_export_clip(file_path: str, task: str = Query(None)):
    task_name = task or args.task
    from handlers.media import serve_task_file
    path, mime = serve_task_file(task_name, f"/export_clips/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime,
                        headers={"Accept-Ranges": "bytes"})


@app.get("/posters/{file_path:path}")
def api_serve_poster(file_path: str):
    from handlers.media import serve_poster
    path, mime = serve_poster(f"/posters/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime)


# ═══════════════════════════════════════════════════════════════
# POST 端点 — 任务 CRUD
# ═══════════════════════════════════════════════════════════════

@app.post("/tasks/create")
async def api_create_task(
    drama: str = Form(None),
    name: str = Form(None),
    local_path: str = Form(None),
    docx: UploadFile = File(None),
    audio: UploadFile = File(None),
):
    """创建任务 — 支持 JSON 或 multipart"""
    from handlers.tasks import create_task

    data = {"drama": drama or "", "name": name or "", "local_path": local_path or ""}
    docx_bytes = await docx.read() if docx else None
    audio_bytes = await audio.read() if audio else None
    docx_name = docx.filename if docx else "解说文案.docx"
    audio_name = audio.filename if audio else "解说音频.wav"

    return create_task(data, docx_bytes, audio_bytes, docx_name, audio_name)


@app.post("/tasks/create_json")
async def api_create_task_json(request: Request):
    """创建任务 — JSON body（兼容前端非 multipart 调用）"""
    from handlers.tasks import create_task
    data = await request.json()
    return create_task(data)


@app.post("/tasks/status")
async def api_update_task_status(request: Request):
    from handlers.tasks import update_task_status
    data = await request.json()
    drama_name = data.get("drama", project_name)
    task_name = data.get("name", "")
    status = data.get("status", "")
    return update_task_status(drama_name, task_name, status)


@app.post("/tasks/delete")
async def api_delete_task(request: Request):
    from handlers.tasks import delete_task
    data = await request.json()
    drama_name = data.get("drama", project_name)
    task_name = data.get("name", "")
    return delete_task(drama_name, task_name)


# ═══════════════════════════════════════════════════════════════
# POST 端点 — 剪辑操作
# ═══════════════════════════════════════════════════════════════

@app.post("/assign")
async def api_assign(request: Request):
    from handlers.media import assign_clip
    data = await request.json()
    task_name = data.get("task", args.task)
    return assign_clip(task_name, data)


@app.post("/copy")
async def api_copy_clip(request: Request):
    from handlers.media import copy_clip
    data = await request.json()
    task_name = data.get("task", args.task)
    return copy_clip(task_name, data)


@app.post("/thumb")
async def api_thumb(request: Request):
    from handlers.media import extract_clip
    data = await request.json()
    return extract_clip(data.get("ep", 1), float(data.get("start", 0)),
                        float(data.get("end", 0)), full=False)


@app.post("/download")
async def api_download(request: Request):
    from handlers.media import download_clip
    data = await request.json()
    task_name = data.get("task", args.task)
    return download_clip(task_name, data.get("ep", 1),
                         float(data.get("start", 0)), float(data.get("end", 0)))


# ═══════════════════════════════════════════════════════════════
# POST 端点 — AI
# ═══════════════════════════════════════════════════════════════

@app.post("/chat")
async def api_chat(request: Request):
    from handlers.dialogue import chat
    data = await request.json()
    messages = data.get("messages", [])
    context = data.get("context", {})
    eps = data.get("eps", None)
    return chat(messages, context, eps)


@app.post("/dialogue_match")
async def api_dialogue_match(request: Request):
    from handlers.dialogue import dialogue_match
    data = await request.json()
    return dialogue_match(data.get("dialogue", ""))


@app.post("/storyboard_suggest")
async def api_storyboard_suggest(request: Request):
    from handlers.storyboard import storyboard_suggest
    data = await request.json()
    return storyboard_suggest(
        data.get("narration", ""),
        segment_context=data.get("segment_context"),
        cover=data.get("cover", ""),
        prev_highlight=data.get("prev_highlight", ""),
        next_highlight=data.get("next_highlight", ""),
        focus_episodes=data.get("focus_episodes", []),
    )


@app.post("/script/analyze_transcript")
async def api_analyze_transcript(request: Request):
    from handlers.storyboard import analyze_transcript
    data = await request.json()
    return analyze_transcript(data.get("transcript", ""))


@app.post("/script/generate_from_outline")
async def api_generate_from_outline(request: Request):
    from handlers.storyboard import generate_from_outline
    data = await request.json()
    return generate_from_outline(
        data.get("topic", ""),
        data.get("outline", []),
        data.get("transcript", ""),
    )


@app.post("/script/generate_script")
async def api_generate_script(request: Request):
    from handlers.script_gen import generate_script
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)
    return generate_script(topic)


# ═══════════════════════════════════════════════════════════════
# POST 端点 — SSE 流式
# ═══════════════════════════════════════════════════════════════

def _sse_gen(inner_fn, *args):
    """通用 SSE 生成器包装器"""
    import queue
    q = queue.Queue()

    def _emit(event, data):
        q.put(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")

    heartbeat_active = [True]

    def _heartbeat():
        while heartbeat_active[0]:
            time.sleep(15)
            try:
                q.put(f"event: heartbeat\ndata: {json.dumps({'ts': time.time()})}\n\n")
            except Exception:
                break

    threading.Thread(target=_heartbeat, daemon=True).start()

    def _run():
        try:
            inner_fn(*args, _emit)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                _emit("error", {"error": str(e)[:200]})
            except Exception:
                pass
        finally:
            time.sleep(0.5)
            heartbeat_active[0] = False
            q.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    while True:
        chunk = q.get()
        if chunk is None:
            break
        yield chunk


@app.post("/script/generate_script_stream")
async def api_generate_script_stream(request: Request):
    """v3 Agent 流水线 SSE"""
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)

    from handlers.script_gen import generate_script_stream

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})

        def emit_complete(result):
            emit("complete", result)

        def emit_error(error, detail=""):
            emit("error", {"error": error, "detail": detail})

        generate_script_stream(topic, emit_progress, emit_complete, emit_error)

    return StreamingResponse(_sse_gen(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/script/generate_story_first")
async def api_generate_story_first(request: Request):
    """v4 故事优先 SSE"""
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)

    from handlers.script_gen import generate_story_first

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})

        def emit_complete(result):
            emit("complete", result)

        def emit_error(error, detail=""):
            emit("error", {"error": error, "detail": detail})

        generate_story_first(topic, emit_progress, emit_complete, emit_error)

    return StreamingResponse(_sse_gen(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/script/refine")
async def api_refine(request: Request):
    """精切 SSE"""
    from handlers.script_gen import refine_segments

    def _run(task_name, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})

        def emit_complete(result):
            emit("complete", result)

        def emit_error(error, detail=""):
            emit("error", {"error": error, "detail": detail})

        refine_segments(task_name, emit_progress, emit_complete, emit_error)

    return StreamingResponse(_sse_gen(_run, args.task), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


class DramaScriptRequest(BaseModel):
    topic: str
    episodes: Optional[list[int]] = None
    target_duration: int = 480
    drama: Optional[str] = None


@app.post("/script/generate_drama_script")
async def api_generate_drama_script(body: DramaScriptRequest):
    """编剧Agent SSE — 电视剧解说脚本生成"""
    from handlers.script_drama import generate_drama_script

    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供选题描述 (topic)"}, status_code=400)

    drama_name = body.drama or project_name
    focus_episodes = body.episodes
    target_duration = body.target_duration

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})

        def emit_complete(result):
            emit("complete", result)

        def emit_error(error, detail=""):
            emit("error", {"error": error, "detail": detail})

        generate_drama_script(
            topic=topic,
            emit_progress=emit_progress,
            emit_complete=emit_complete,
            emit_error=emit_error,
            drama_name=drama_name,
            focus_episodes=focus_episodes,
            target_duration=target_duration,
        )

    return StreamingResponse(_sse_gen(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


# ═══════════════════════════════════════════════════════════════
# POST 端点 — 流水线 + 导出
# ═══════════════════════════════════════════════════════════════

@app.get("/data/quality")
def api_data_quality(project: str = "都挺好"):
    """返回每集的数据质量统计，供 DataDesk 展示"""
    import os, json
    from pathlib import Path

    drama_dir = Path(__file__).resolve().parent.parent / project
    episodes = []

    for ep in range(1, 47):
        ep_dir = drama_dir / "sources" / f"ep{ep}"

        # ── 检测数据文件 ──
        has_vlm = (ep_dir / "vlm_seg_cache_v3.json").exists()
        has_asr = (ep_dir / "asr_result.json").exists()
        has_scene_map = (ep_dir / "scene_map.json").exists()
        has_synopsis = (ep_dir / "ep_synopsis.json").exists()

        # ── 计数 ──
        vlm_count = 0
        if has_vlm:
            try:
                vlm_count = len(json.load(open(ep_dir / "vlm_seg_cache_v3.json")))
            except: pass

        asr_count = 0
        if has_asr:
            try:
                asr_count = len(json.load(open(ep_dir / "asr_result.json")))
            except: pass

        scene_map_count = 0
        scene_map_quality = 0  # 场景描述完整度: 0-100
        if has_scene_map:
            try:
                sm = json.load(open(ep_dir / "scene_map.json"))
                scene_map_count = len(sm)
                # 计算场景描述的完整度: event + mood 都有 = 高分
                complete = sum(1 for s in sm if s.get("event") and s.get("mood"))
                scene_map_quality = round(complete / max(scene_map_count, 1) * 100, 1)
            except: pass

        # ── 综合评分 ──
        # 四个维度: ASR(25%) + VLM(30%) + scene_map(30%) + synopsis(15%)
        asr_score = min(100, asr_count * 0.1) if asr_count > 0 else 0  # 每10句ASR≈1分
        vlm_score = min(100, vlm_count * 4) if vlm_count > 0 else 0   # 每段VLM≈4分，25段=100
        sm_score = scene_map_quality                                     # 场景完整度
        syn_score = 100 if has_synopsis else 0

        overall = round(
            asr_score * 0.25 +
            vlm_score * 0.30 +
            sm_score * 0.30 +
            syn_score * 0.15
        , 1)

        episodes.append({
            "ep": ep,
            "vlm": vlm_count,
            "asr": asr_count,
            "scene_map": scene_map_count,
            "has_vlm": has_vlm,
            "has_asr": has_asr,
            "has_scene_map": has_scene_map,
            "has_synopsis": has_synopsis,
            "vlm_score": round(vlm_score, 1),
            "asr_score": round(asr_score, 1),
            "scene_map_score": sm_score,
            "synopsis_score": syn_score,
            "overall_score": overall,
        })

    # 汇总
    total_eps = 46
    eps_with_data = sum(1 for e in episodes if e["has_vlm"] or e["has_asr"])
    avg_score = round(sum(e["overall_score"] for e in episodes) / total_eps, 1)

    return {
        "project": project,
        "episodes": episodes,
        "total": total_eps,
        "summary": {
            "total_eps": total_eps,
            "eps_with_data": eps_with_data,
            "avg_score": avg_score,
            "total_vlm_scenes": sum(e["vlm"] for e in episodes),
            "total_asr_segments": sum(e["asr"] for e in episodes),
            "total_scene_maps": sum(e["scene_map"] for e in episodes),
        },
    }

@app.post("/data/process")
async def api_data_process(request: Request):
    from handlers.pipeline import run_pipeline, run_interview_pipeline, get_process_status

    data = await request.json()
    drama_name = data.get("drama", project_name)
    episodes = data.get("episodes", [])

    if project_type == "interview":
        task_name = data.get("task_name", args.task)
        task_id = f"interview_{task_name}_{int(time.time())}"
        run_interview_pipeline(task_id, task_name)
    else:
        task_id = f"{drama_name}_{'_'.join(str(e) for e in episodes)}_{int(time.time())}"
        run_pipeline(task_id, episodes, drama_name)

    return {"ok": True, "task_id": task_id}


@app.get("/data/status")
def api_data_status(task_id: str = Query(None)):
    from handlers.pipeline import get_process_status
    if not task_id:
        return JSONResponse({"ok": False, "error": "missing task_id"}, status_code=400)
    return get_process_status(task_id)


@app.post("/export/extract_clips")
async def api_export_extract_clips(request: Request):
    from handlers.media import export_extract_clips
    data = await request.json()
    task_name = data.get("task", args.task)
    clips = data.get("clips", [])
    if not clips:
        return JSONResponse({"ok": False, "error": "no clips provided"}, status_code=400)
    return export_extract_clips(task_name, clips)


@app.post("/picks")
async def api_picks(request: Request):
    """同步 picks 到 SQLite"""
    data = await request.json()
    drama_name = data.get("drama", project_name)
    task_name = data.get("task", args.task)
    picks = data.get("picks", [])

    drama_id = db.get_drama_id(drama_name)
    if not drama_id:
        drama_id = db.ensure_drama(drama_name)

    # 获取或创建 task
    existing = db.get_task(drama_id, task_name)
    if existing:
        task_id = existing["id"]
    else:
        task_id = db.create_task(drama_id, task_name)

    # 写 segments 的 picks 关联
    picks_map = {}
    for p in picks:
        seg_id = p.get("seg_id")
        if seg_id is not None:
            picks_map[seg_id] = p

    segments = db.get_task_segments(task_id)
    for seg in segments:
        sid = seg.get("seg_id")
        if sid in picks_map:
            seg["picked"] = picks_map[sid]

    db.save_task_segments(task_id, segments)
    return {"ok": True, "synced": len(picks)}


# ═══════════════════════════════════════════════════════════════
# 静态文件 — SPA fallback（放在最后确保 API 优先匹配）
# ═══════════════════════════════════════════════════════════════

# 任务目录静态文件（兜底）
@app.get("/{filename:path}")
def api_task_static(filename: str, task: str = Query(None)):
    """任务目录下的各类文件（docx, json, mp4, wav 等）"""
    task_name = task or args.task
    from handlers.static import get_static_file
    file_path, mime = get_static_file(resolve_task_dir(task_name), f"/{filename}")
    if file_path:
        return FileResponse(file_path, media_type=mime)
    raise HTTPException(404)


# ═══════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
