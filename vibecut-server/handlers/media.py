"""媒体服务 — 代理视频、批量导出、文件服务"""

import json
import subprocess
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

from config import (
    project_name, PROJECT_DIR, BASE_DIR, PROXY_DIR, PROXY_MANIFEST,
    SOURCE_VIDEOS, args,
)


# ── 代理视频 ──
def get_proxy_manifest() -> dict:
    if PROXY_MANIFEST.exists():
        return json.loads(PROXY_MANIFEST.read_text())
    return {"drama": project_name, "proxies": [], "note": "无代理文件，请先运行 generate_proxies.py"}


# ── 批量导出 ──
def export_extract_clips(task_name: str, clips: list) -> dict:
    """从 1080p 原剧批量提取 clip 片段"""
    by_ep = {}
    for c in clips:
        ep = c["ep"]
        if ep not in by_ep:
            by_ep[ep] = []
        by_ep[ep].append(c)

    task_dir = PROJECT_DIR / "tasks" / task_name
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

            if out_path.exists() and not c.get("overwrite"):
                extracted.append({"ep": ep, "outputName": out_name,
                                  "url": f"/export_clips/{out_name}?task={task_name}"})
                continue

            start = c["start"]
            dur = c["end"] - c["start"]
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", str(start), "-t", str(dur), "-i", str(src_path),
                   "-c", "copy", "-avoid_negative_ts", "make_zero", str(out_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and out_path.exists():
                extracted.append({"ep": ep, "outputName": out_name,
                                  "url": f"/export_clips/{out_name}?task={task_name}",
                                  "duration": dur})
                print(f"[export] EP{ep} {start}s-{c['end']}s → {out_name}")
            else:
                print(f"[export] EP{ep} 提取失败: {result.stderr[:200]}")

    return {"ok": True, "clips": extracted, "total": len(extracted)}


# ── 文件服务（任务目录静态文件） ──
def serve_task_file(task_name: str, req_path: str) -> tuple[Path | None, str]:
    """解析任务目录下的文件路径，返回 (file_path, mime_type)"""
    clean = unquote(urlparse(req_path).path.lstrip("/"))
    if "?" in clean:
        clean = clean.split("?")[0]
    if "tts_segments/" in clean:
        path = PROJECT_DIR / "tasks" / task_name / "work_dir" / clean
    elif "export_clips/" in clean:
        path = PROJECT_DIR / "tasks" / task_name / clean
    else:
        clean = clean.replace("clips/", "素材clips/")
        path = PROJECT_DIR / "tasks" / task_name / clean
    if not path.exists():
        return None, ""
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".mp4": "video/mp4", ".wav": "audio/wav",
    }
    return path, mime_map.get(ext, "application/octet-stream")


# ── Poster 服务 ──
def serve_poster(path: str) -> tuple[Path | None, str]:
    """解析 poster 路径"""
    parts = unquote(path).strip("/").split("/")
    if len(parts) >= 3:
        drama_name = parts[1]
        filename = parts[2]
        file_path = BASE_DIR / drama_name / "posters" / filename
        if file_path.exists():
            return file_path, "image/jpeg"
    return None, ""
