"""路由: 分镜脚本导入 (POST /storyboard/import)

接收扣子/WorkBuddy 产出的全局分镜脚本，原样落盘到任务目录 storyboard.json。

阶段 A（最小验证）：只落盘 + 返回统计，不做预剪辑/归一化。
- 幂等覆盖：同 task 最后一次传入覆盖之前，不追加。
- 自动建目录：task 名不存在则创建（复用 resolve_task_dir）。
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import resolve_task_dir

router = APIRouter(tags=["分镜"])


@router.post("/storyboard/import")
async def api_storyboard_import(request: Request):
    body = await request.json()
    task_name = body.get("task") or ""
    storyboard = body.get("storyboard")

    if not task_name:
        return JSONResponse({"ok": False, "error": "缺少 task 字段"}, status_code=400)
    if not isinstance(storyboard, dict):
        return JSONResponse({"ok": False, "error": "缺少 storyboard 对象"}, status_code=400)

    # 统计（扣子契约: segments[] 内每段含 shot_sequence[]）
    segments = storyboard.get("segments", []) if isinstance(storyboard.get("segments"), list) else []
    total_shots = 0
    for seg in segments:
        seq = seg.get("shot_sequence", []) if isinstance(seg, dict) else []
        total_shots += len(seq)

    # 落盘（原样，不归一化）
    task_dir = resolve_task_dir(task_name)
    task_dir.mkdir(parents=True, exist_ok=True)
    out_path = task_dir / "storyboard.json"
    import json
    json.dump(storyboard, open(out_path, "w"), ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "task": task_name,
        "total_segments": len(segments),
        "total_shots": total_shots,
        "file": str(out_path),
    }
