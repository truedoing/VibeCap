"""编剧台 Drama SSE 处理函数 — POST /script/generate_drama_script

对标 handlers/script_gen.py 的模式：
  generate_drama_script() 作为 SSE 回调函数
  负责加载数据 → 调用 Agent → 保存结果 → 发送 SSE 事件
"""

import json
import os
import time
from pathlib import Path

from config import project_name, PROJECT_DIR, BASE_DIR, args
from db import VibeCutDB

DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


# ── 论点阶段缓存（两段式：避免 generate_thesis → generate_drama_script 重跑故事师）──
def _thesis_cache_path() -> Path:
    """论点阶段的故事地图缓存文件（按 task 隔离）"""
    tasks_dir = PROJECT_DIR / "tasks"
    task_dir = tasks_dir / (args.task or "default")
    return task_dir / "thesis_cache.json"


def _save_thesis_cache(topic: str, story_map: dict, candidates: list):
    """落盘故事地图 + 候选论点，供下一步 generate_drama_script 复用。"""
    cache_path = _thesis_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"topic": topic, "story_map": story_map, "candidates": candidates},
              open(cache_path, "w"), ensure_ascii=False, indent=2)


def _load_thesis_cache(topic: str) -> dict:
    """读回缓存的故事地图（校验 topic 一致，防止串台）。"""
    cache_path = _thesis_cache_path()
    if not cache_path.exists():
        return {}
    try:
        data = json.load(open(cache_path))
    except Exception:
        return {}
    if data.get("topic") != topic:
        return {}
    return data


def generate_thesis(topic: str, drama_name: str = None) -> dict:
    """论点阶段（非 SSE，普通 JSON）：跑故事师 → 论点师，产出候选论点 + 缓存故事地图。

    返回 {"ok": True, "topic": ..., "candidates": [...], "story_map": {...}}
    """
    from agents.drama_script_agents import (
        story_master_agent, thesis_agent,
        _extract_key_episodes_from_story_map, _load_scene_maps,
    )

    drama = drama_name or project_name

    # 复用缓存：同一 topic 已跑过故事师则直接返回
    cached = _load_thesis_cache(topic)
    if cached:
        return {"ok": True, "topic": topic, "candidates": cached.get("candidates", []),
                "story_map": cached.get("story_map", {}), "cached": True}

    story_res = story_master_agent(PROJECT_DIR, drama, None)
    if not story_res.get("ok"):
        return {"ok": False, "error": f"故事师失败: {story_res.get('error', '?')}"}

    story_map = story_res["result"]

    # 从故事师弧光提取聚焦剧集，加载其 scene_map，让论点师锚定具体事件
    focus_eps = _extract_key_episodes_from_story_map(story_map, topic) or []
    scene_maps = _load_scene_maps(PROJECT_DIR, focus_eps) if focus_eps else None

    thesis_res = thesis_agent(story_map, topic, scene_maps=scene_maps, focus_eps=focus_eps)
    if not thesis_res.get("ok"):
        return {"ok": False, "error": f"论点师失败: {thesis_res.get('error', '?')}"}

    candidates = thesis_res["result"].get("candidates", [])
    if not candidates:
        return {"ok": False, "error": "论点师未产出候选论点"}

    _save_thesis_cache(topic, story_map, candidates)
    return {"ok": True, "topic": topic, "candidates": candidates, "story_map": story_map}


def generate_drama_script(
    topic: str,
    emit_progress,
    emit_complete,
    emit_error,
    *,
    drama_name: str = None,
    focus_episodes: list = None,
    target_duration: int = 480,
    thesis: dict = None,
):
    """编剧 Agent SSE 主流程

    对标 generate_story_first() ——
      1. 加载/准备数据（含复用论点阶段缓存的故事地图）
      2. 调用 Agent 编排器
      3. 保存结果
      4. 发送 complete/error 事件
    """
    from agents.drama_script_agents import run_drama_pipeline

    drama = drama_name or project_name
    emit_progress("init", f"🎬 编剧Agent启动 · 剧目: {drama} · 选题: {topic[:40]}")

    # 两段式：若传了 thesis，优先复用论点阶段缓存的故事地图（避免重跑故事师）
    story_map = None
    if thesis:
        cached = _load_thesis_cache(topic)
        if cached:
            story_map = cached.get("story_map")
            emit_progress("init", "📚 复用论点阶段的故事地图缓存，跳过故事师")

    # 调用 Agent 编排器
    result = run_drama_pipeline(
        project_dir=PROJECT_DIR,
        topic=topic,
        drama_name=drama,
        focus_episodes=focus_episodes,
        target_duration=target_duration,
        thesis=thesis,
        story_map=story_map,
        emit_progress=lambda step, msg, data=None:
            emit_progress(step, msg, data),
    )

    if result.get("ok") and result.get("segments") and len(result["segments"]) > 0:
        # 保存到文件和数据库
        _save_drama_segments(result, topic)
        _save_to_task_dir(result)
        _sync_to_db(result)
        emit_complete(result)
    else:
        emit_error(
            result.get("error", "生成失败: 未产出有效文案"),
            str(result.get("detail", ""))[:200],
        )


# ── 辅助函数 ──

def _save_drama_segments(result: dict, topic: str):
    """保存到项目级 tasks/ 目录 (和 interview 一样)"""
    tasks_dir = PROJECT_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    script_file = tasks_dir / "文案脚本.json"
    save_data = {
        "pipeline": "drama-agent-v1",
        "topic": topic,
        "cover": result.get("cover", ""),
        "thesis": result.get("thesis"),
        "story": result.get("story_map", {}).get("character_arcs", [{}])[0].get("arc_summary", "")
            if result.get("story_map", {}).get("character_arcs") else "",
        "chapters": result.get("chapter_structure", {}).get("chapters", []),
        "segments": result["segments"],
        "total": result.get("total", len(result["segments"])),
        "time_estimate": result.get("time_estimate", {}),
        "review_verdict": result.get("review_verdict", "?"),
        "review_issues": result.get("review_issues", []),
        # 选题推荐：故事师已产出，此前被精简 schema 丢弃
        "topic_suggestions": result.get("story_map", {}).get("topic_suggestions", []),
        "highlight_scenes": result.get("story_map", {}).get("highlight_scenes", []),
    }
    json.dump(save_data, open(script_file, "w"), ensure_ascii=False, indent=2)
    result["script_file"] = str(script_file)
    print(f"[drama_script] 保存文案脚本 → {script_file}")


def _save_to_task_dir(result: dict):
    """同步写入任务级 segments.json (兼容 VibeEdit 加载)"""
    tasks_dir = PROJECT_DIR / "tasks"
    task_dir = tasks_dir / (args.task or "default")
    task_dir.mkdir(parents=True, exist_ok=True)

    seg_file = task_dir / "segments.json"

    # 提取 hook 行和收尾行
    hook_line = ""
    closing_line = ""
    for s in result["segments"]:
        narr = s.get("narration_text", "")
        chap = s.get("chapter_title", "")
        if ("hook" in chap.lower() or "开场" in chap or s.get("seg_id") == 0) and not hook_line:
            hook_line = narr[:60]
        if ("收尾" in chap or "洞察" in chap or "closing" in chap.lower()) and not closing_line:
            closing_line = narr[:60]

    seg_data = {
        "task_type": "drama",
        "source": "AI编剧Agent",
        "pipeline": "drama-agent-v1",
        "project_type": "drama",
        "total_segments": len(result["segments"]),
        "target_duration": result.get("time_estimate", {}).get("target", 480),
        "cover": result.get("cover", ""),
        "hook_line": hook_line,
        "closing_line": closing_line,
        "audio_verified": False,
        "segments": result["segments"],
    }
    json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)
    print(f"[drama_script] segments.json 同步 → {seg_file}")


def _sync_to_db(result: dict):
    """同步写入 SQLite (和 interview 一样)"""
    try:
        drama_id = db.get_drama_id(project_name)
        if drama_id:
            task_name = args.task or f"drama_{int(time.time())}"
            existing = db.get_task(drama_id, task_name)
            if existing:
                task_id = existing["id"]
                db.save_task_segments(task_id, result["segments"])
            else:
                task_id = db.create_task(drama_id, task_name)
                db.save_task_segments(task_id, result["segments"])
            print(f"[drama_script] DB: task={task_name} task_id={task_id} segs={len(result['segments'])}")
            result["task_id"] = task_id
    except Exception as e:
        print(f"[drama_script] DB save failed (non-critical): {e}")
