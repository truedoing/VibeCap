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


@router.get("/posters/{file_path:path}")
def api_serve_poster(file_path: str):
    from handlers.media import serve_poster
    path, mime = serve_poster(f"/posters/{file_path}")
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=mime)


# ── 剪辑操作 ──
@router.post("/assign")
async def api_assign(request: Request):
    from handlers.media import assign_clip
    data = await request.json()
    return assign_clip(data.get("task", args.task), data)


@router.post("/copy")
async def api_copy_clip(request: Request):
    from handlers.media import copy_clip
    data = await request.json()
    return copy_clip(data.get("task", args.task), data)


@router.post("/thumb")
async def api_thumb(request: Request):
    from handlers.media import extract_clip
    data = await request.json()
    return extract_clip(data.get("ep", 1), float(data.get("start", 0)),
                        float(data.get("end", 0)), full=False)


@router.post("/download")
async def api_download(request: Request):
    from handlers.media import download_clip
    data = await request.json()
    return download_clip(data.get("task", args.task), data.get("ep", 1),
                         float(data.get("start", 0)), float(data.get("end", 0)))
