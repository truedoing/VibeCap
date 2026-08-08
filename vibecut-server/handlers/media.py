"""媒体服务 — 代理视频、片段提取/预览/下载/导出、缩略图、文件服务"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from config import (
    project_name, PROJECT_DIR, BASE_DIR, PROXY_DIR, PROXY_MANIFEST,
    SOURCE_VIDEOS, args,
)


# ── 代理视频 ──
def get_proxy_manifest() -> dict:
    if PROXY_MANIFEST.exists():
        return json.loads(PROXY_MANIFEST.read_text())
    return {"drama": project_name, "proxies": [], "note": "无代理文件，请先运行 generate_proxies.py"}


def find_proxy_path(path: str) -> Path | None:
    """解析代理视频文件路径"""
    clean = unquote(path).lstrip("/")
    filename = clean.split("/")[-1]
    file_path = PROXY_DIR / filename
    return file_path if file_path.exists() else None


# ── 片段提取（搜索预览用） ──
def extract_clip(ep, start, end, full=False, clip_dir=None) -> dict:
    if clip_dir is None:
        clip_dir = PROJECT_DIR / "tasks" / (args.task or "default") / "素材clips"
    src = SOURCE_VIDEOS.get(f"ep{ep}")
    if not src:
        return {"error": "src not found"}
    name = f"clip_search_ep{ep}_{int(start)}s.mp4"
    out = clip_dir / name
    if full:
        subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-i", str(src),
                        "-t", str(end - start),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "192k",
                        str(out)], capture_output=True)
    thumb = clip_dir / (name.rsplit('.', 1)[0] + '.jpg')
    mid = start + (end - start) / 2
    subprocess.run(["ffmpeg", "-y", "-ss", str(mid), "-i", str(src),
                    "-vframes", "1", "-q:v", "3", str(thumb)], capture_output=True)
    result = {"ok": True, "duration": round(end - start, 1), "thumb": thumb.name}
    if full:
        result["file"] = name
    return result


# ── 预览视频生成 ──
def serve_preview(ep, t, sid="default", task=None, end_t=None) -> dict:
    task_name = task or args.task
    clip_dir = PROJECT_DIR / "tasks" / task_name / "素材clips"
    src = SOURCE_VIDEOS.get(f"ep{ep}")
    if not src:
        return {"ok": False, "error": "src not found"}

    tmp = clip_dir / f"_pv_{sid}.mp4"
    if end_t and end_t > t:
        clip_start = max(0, t - 1)
        clip_end = end_t + 1
        duration = clip_end - clip_start
    else:
        clip_start = max(0, t - 2)
        clip_end = clip_start + 20
        duration = 20

    subprocess.run(["ffmpeg", "-y", "-ss", str(clip_start), "-i", str(src),
                    "-t", str(duration), "-vf", "scale=640:360",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "28", "-c:a", "aac", "-b:a", "64k",
                    str(tmp)], capture_output=True)
    if tmp.exists():
        return {"ok": True, "file": tmp.name, "url": f"/clips/{tmp.name}?task={task_name}",
                "start": clip_start, "end": clip_end}
    return {"ok": False, "error": "preview generation failed"}


# ── 高清下载 ──
def download_clip(task_name: str, ep, start, end) -> dict:
    clip_dir = PROJECT_DIR / "tasks" / task_name / "素材clips"
    src = SOURCE_VIDEOS.get(f"ep{ep}")
    if not src:
        return {"ok": False, "error": "源视频未找到"}

    def fmt(sec):
        m, s = int(sec // 60), int(sec % 60)
        return f"{m}m{s:02d}s"

    name = f"clip_EP{ep}_{fmt(start)}_to_{fmt(end)}.mp4"
    out = clip_dir / name
    if out.exists():
        return {"ok": True, "file": name, "url": f"/clips/{name}?task={task_name}", "cached": True}

    # 后台提取
    def _extract():
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-i", str(src),
            "-t", str(end - start),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "256k",
            str(out)
        ], capture_output=True)
    threading.Thread(target=_extract, daemon=True).start()
    return {"ok": True, "file": name, "status": "extracting"}


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


# ── assign/copy/thumb 辅助函数 ──
def assign_clip(task_name: str, data: dict) -> dict:
    import shutil
    clip_dir = PROJECT_DIR / "tasks" / task_name / "素材clips"

    if data.get("pv_file"):
        src = clip_dir / data["pv_file"]
        dst_name = f"clip_pick_S{data.get('sid', '0')}_{data.get('seq', '0')}_{data.get('type', 'main')}_ep{data.get('ep', '0')}.mp4"
        dst = clip_dir / dst_name
        shutil.copy(str(src), str(dst))
        thumb = clip_dir / (dst_name.rsplit('.', 1)[0] + '.jpg')
        mid = float(data.get("start", 0)) + (float(data.get("end", 0)) - float(data.get("start", 0))) / 2
        src_video = SOURCE_VIDEOS.get(f"ep{data.get('ep', 27)}", "")
        if src_video:
            subprocess.run(["ffmpeg", "-y", "-ss", str(mid), "-i", str(src_video),
                            "-vframes", "1", "-q:v", "3", str(thumb)], capture_output=True)
        return {"ok": True, "file": dst_name, "thumb": thumb.name}
    else:
        return extract_clip(data["ep"], max(0, float(data["start"]) - 2),
                            float(data["end"]) + 2, full=True, clip_dir=clip_dir)


def copy_clip(task_name: str, data: dict) -> dict:
    import shutil
    clip_dir = PROJECT_DIR / "tasks" / task_name / "素材clips"
    pv_file = data.get("pv_file", "")
    src = clip_dir / pv_file
    if not pv_file or not src.exists():
        return {"ok": False, "error": f"pv_file not found: {pv_file}"}

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
        subprocess.run(["ffmpeg", "-y", "-ss", str(mid), "-i", str(src_video),
                        "-vframes", "1", "-q:v", "3", str(thumb)], capture_output=True)
    return {"ok": True, "file": dst_name, "thumb": thumb_name}


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
