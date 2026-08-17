"""路由: 数据流水线 + 质量报告"""
import json
from pathlib import Path
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from config import project_name, project_type, args

router = APIRouter(prefix="/data", tags=["流水线"])


@router.get("/quality")
def api_data_quality(project: str = "都挺好"):
    """返回每集的数据质量统计，供 DataDesk 展示"""
    # routers/pipeline.py → vibecut-server/ → VIBECAP/（项目数据在 VIBECAP/ 下）
    drama_dir = Path(__file__).resolve().parent.parent.parent / project
    episodes = []

    for ep in range(1, 47):
        ep_dir = drama_dir / "sources" / f"ep{ep}"
        has_vlm = (ep_dir / "vlm_seg_cache_v3.json").exists()
        has_asr = (ep_dir / "subtitle_result.json").exists()
        has_scene_map = (ep_dir / "scene_map.json").exists()
        has_synopsis = (ep_dir / "ep_synopsis.json").exists()

        vlm_count = 0
        if has_vlm:
            try: vlm_count = len(json.load(open(ep_dir / "vlm_seg_cache_v3.json")))
            except: pass

        asr_count = 0
        if has_asr:
            try: asr_count = len(json.load(open(ep_dir / "subtitle_result.json")))
            except: pass

        scene_map_count = 0
        scene_map_quality = 0
        if has_scene_map:
            try:
                sm = json.load(open(ep_dir / "scene_map.json"))
                scene_map_count = len(sm)
                complete = sum(1 for s in sm if s.get("event") and s.get("mood"))
                scene_map_quality = round(complete / max(scene_map_count, 1) * 100, 1)
            except: pass

        asr_score = min(100, asr_count * 0.1) if asr_count > 0 else 0
        vlm_score = min(100, vlm_count * 4) if vlm_count > 0 else 0
        sm_score = scene_map_quality
        syn_score = 100 if has_synopsis else 0

        overall = round(
            asr_score * 0.25 + vlm_score * 0.30 + sm_score * 0.30 + syn_score * 0.15, 1)

        episodes.append({
            "ep": ep, "vlm": vlm_count, "asr": asr_count, "scene_map": scene_map_count,
            "has_vlm": has_vlm, "has_asr": has_asr, "has_scene_map": has_scene_map,
            "has_synopsis": has_synopsis,
            "vlm_score": round(vlm_score, 1), "asr_score": round(asr_score, 1),
            "scene_map_score": sm_score, "synopsis_score": syn_score,
            "overall_score": overall,
        })

    total_eps = 46
    avg_score = round(sum(e["overall_score"] for e in episodes) / total_eps, 1)

    return {
        "project": project, "episodes": episodes, "total": total_eps,
        "summary": {
            "total_eps": total_eps,
            "eps_with_data": sum(1 for e in episodes if e["has_vlm"] or e["has_asr"]),
            "avg_score": avg_score,
            "total_vlm_scenes": sum(e["vlm"] for e in episodes),
            "total_asr_segments": sum(e["asr"] for e in episodes),
            "total_scene_maps": sum(e["scene_map"] for e in episodes),
        },
    }


@router.post("/process")
async def api_data_process(request: Request):
    import time
    from handlers.pipeline import run_pipeline, run_interview_pipeline

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


@router.get("/status")
def api_data_status(task_id: str = Query(None)):
    from handlers.pipeline import get_process_status
    if not task_id:
        return JSONResponse({"ok": False, "error": "missing task_id"}, status_code=400)
    return get_process_status(task_id)


@router.get("/process_status")
def api_data_process_status(task_id: str = Query(None)):
    """数据台加工进度轮询（前端 DataDesk 使用此路径）"""
    from handlers.pipeline import get_process_status
    if not task_id:
        return JSONResponse({"ok": False, "error": "missing task_id"}, status_code=400)
    return get_process_status(task_id)
