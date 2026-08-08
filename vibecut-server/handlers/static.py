"""SPA 前端回退 — 生产构建静态文件服务"""

from pathlib import Path
from config import FRONTEND_DIR


MIME_MAP = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}

API_PREFIXES = (
    "/clips/", "/素材clips/", "/tts_segments/", "/posters/",
    "/proxies/", "/export_clips/",
)

API_ROUTES = {
    "/search", "/chat", "/segments.json", "/preview_video", "/status",
    "/dramas", "/tasks", "/assign", "/copy", "/thumb", "/storyboard_suggest",
    "/narration.json", "/tasks/status", "/tasks/delete",
}


def resolve_frontend_file(path: str) -> tuple[Path | None, str]:
    """尝试解析前端文件，返回 (file_path, mime_type) 或 (None, "")

    - 精确匹配文件 → 返回文件
    - 无后缀路径 → 返回 index.html (SPA fallback)
    """
    if not FRONTEND_DIR.exists():
        return None, ""

    clean = path.lstrip("/")

    # API 路由不处理
    if path in API_ROUTES:
        return None, ""
    for prefix in API_PREFIXES:
        if path.startswith(prefix):
            return None, ""

    # 精确文件匹配
    file_path = FRONTEND_DIR / clean if clean else FRONTEND_DIR / "index.html"
    if file_path.exists() and file_path.is_file():
        ext = file_path.suffix.lower()
        return file_path, MIME_MAP.get(ext, "application/octet-stream")

    # SPA fallback
    if "." not in clean.split("/")[-1]:
        index_html = FRONTEND_DIR / "index.html"
        if index_html.exists():
            return index_html, "text/html"

    return None, ""


def get_static_file(task_dir: Path, path: str) -> tuple[Path | None, str]:
    """解析任务目录下的静态文件"""
    from urllib.parse import unquote, urlparse
    clean = unquote(urlparse(path).path.lstrip("/"))
    if "?" in clean:
        clean = clean.split("?")[0]
    file_path = task_dir / clean
    if not file_path.exists() or not file_path.is_file():
        return None, ""
    ext = file_path.suffix.lower()
    ext_mime = {
        ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".json": "application/json", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4",
        ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return file_path, ext_mime.get(ext, "application/octet-stream")
