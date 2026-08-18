"""路由: 媒体服务 (代理/片段/海报) + 剪辑操作"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi import HTTPException
from config import PROXY_DIR, args, resolve_task_dir

router = APIRouter(tags=["媒体"])


@router.get("/proxies/manifest")
def api_proxy_manifest():
    from handlers.media import get_proxy_manifest
    return get_proxy_manifest()


@router.get("/proxies/{filename:path}")
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


@router.get("/clips/{file_path:path}")
def api_serve_clip(file_path: str, task: str = Query(None)):
    task_name = task or args.task
    from handlers.media import serve_task_file
    path, mime = serve_task_file(task_name, f"/clips/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime,
                        headers={"Accept-Ranges": "bytes", "Access-Control-Allow-Origin": "*"})


@router.get("/export_clips/{file_path:path}")
def api_serve_export_clip(file_path: str, task: str = Query(None)):
    task_name = task or args.task
    from handlers.media import serve_task_file
    path, mime = serve_task_file(task_name, f"/export_clips/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime, headers={"Accept-Ranges": "bytes"})


@router.get("/tts_segments/{file_path:path}")
def api_serve_tts(file_path: str, task: str = Query(None)):
    """配音音频文件 (work_dir/tts_segments/narr_*.wav)"""
    task_name = task or args.task
    from handlers.media import serve_task_file
    path, mime = serve_task_file(task_name, f"/tts_segments/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime, headers={"Accept-Ranges": "bytes"})


@router.get("/posters/{file_path:path}")
def api_serve_poster(file_path: str):
    from handlers.media import serve_poster
    path, mime = serve_poster(f"/posters/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime)


@router.get("/thumbs/{ep}/{sec}.jpg")
def api_thumb(ep: int, sec: int):
    """代理视频缩略图 — 按剧集+秒数抽一帧（低分辨率，供时间轴显示）

    缓存到 PROXY_DIR/thumbs/，首次请求用 ffmpeg 抽帧，后续直接返回文件。
    """
    import subprocess
    from config import PROXY_DIR

    # 定位代理视频（优先 manifest，fallback 命名规则）
    proxy_file = None
    try:
        from handlers.media import get_proxy_manifest
        m = get_proxy_manifest()
        hit = next((x for x in m.get("proxies", []) if x.get("ep") == ep), None)
        if hit:
            proxy_file = PROXY_DIR / hit["file"]
    except Exception:
        proxy_file = None
    if not proxy_file or not proxy_file.exists():
        proxy_file = PROXY_DIR / f"都挺好_{ep:02d}_540p.mp4"
    if not proxy_file.exists():
        raise HTTPException(404)

    sec = max(0, int(sec))
    thumb_dir = PROXY_DIR / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    thumb_path = thumb_dir / f"ep{ep:02d}_{sec}.jpg"

    if not thumb_path.exists():
        # 快速 seek 抽帧 + 缩放到 320x180
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-ss", str(sec), "-i", str(proxy_file),
               "-frames:v", "1", "-vf", "scale=320:180", "-q:v", "4", str(thumb_path)]
        subprocess.run(cmd, capture_output=True, text=True)
        if not thumb_path.exists():
            raise HTTPException(404)

    return FileResponse(thumb_path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


