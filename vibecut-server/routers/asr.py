"""路由: ASR 数据"""
import json
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from config import project_name, BASE_DIR

router = APIRouter(prefix="/asr", tags=["ASR"])


@router.get("/raw")
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


@router.get("/classified")
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
