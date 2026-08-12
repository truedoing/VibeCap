"""AI 脚本生成 — 3 个 SSE 端点 + 1 个传统端点"""

import json
import os
import time
import threading
from pathlib import Path

from config import project_name, project_type, PROJECT_DIR, BASE_DIR, args
from db import VibeCutDB

DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


# ── POST /script/generate_script (旧版三步) ──
def generate_script(topic: str) -> dict:
    """三步混编算法生成完整 segments"""
    from lib.llm import call_moonshot_json

    # 加载分类数据
    classified = []
    cf = PROJECT_DIR / "sources_clean" / "classified_学习新东方.json"
    if cf.exists():
        classified = json.load(open(cf))
    content_only = [s for s in classified if s.get('layer') == 'content']
    content_text = '\n'.join(
        f"[{s['start_sec']:.0f}s|imp={s.get('importance', 3)}] {s['text']}"
        for s in content_only
    )

    def _call_llm(system_prompt, user_content, temp=0.4, label="?"):
        result = call_moonshot_json(system_prompt, user_content,
                                    temperature=temp, max_tokens=3000,
                                    timeout=180, label=label)
        if result["ok"]:
            return result["data"]
        raise Exception(result.get("error", "LLM failed"))

    try:
        # Step 1: 大结构
        print("[gen_script] Step 1: 大结构")
        structure = _call_llm(
            "你是短视频策划导演。根据采访内容精华，设计一个60-90秒短视频的5-8段叙事结构。\n\n"
            "★ 硬约束: 各段duration之和必须≤100秒(预留10-20秒缓冲)。\n"
            "★ 每段duration根据内容重要性分配,核心方法论段可15-20秒,过渡段3-5秒。\n\n"
            "要求:\n"
            "1. 确定核心主题(≤15字)\n"
            "2. 每段标注: narrative_role + 核心论点(一句话) + 目标时长(秒)\n"
            "3. narrative_role: hook_tension/hook_promise/personal_reveal/empathy/evidence/bridge/turn/proof/insight\n"
            "4. 结构必须有起伏: 开头激将+个人揭示→方法论→反转→案例→洞察收尾\n"
            "5. 共情层放在方法论之前\n\n"
            "输出JSON: {\"topic\":\"主题\",\"sections\":[{\"role\":\"hook_tension\",\"point\":\"论点\",\"duration\":5}]}",
            f"视频主题方向: {topic}\n\n采访内容精华:\n{content_text[:4000]}",
        )
        total_budget = sum(s.get('duration', 0) for s in structure.get('sections', []))
        print(f"  → {structure.get('topic', '?')}, {len(structure.get('sections', []))} 段, 预算{total_budget}s")

        # Step 2: 组织语句
        print("[gen_script] Step 2: 混编选句")
        all_selected = []
        for i, sec in enumerate(structure.get('sections', [])):
            result = _call_llm(
                "你是短视频精编师。从完整采访ASR中为指定段落选出最合适的原话。\n\n"
                "★ 硬约束: 选句总源时长控制在目标时长的1.3倍以内(留30%精剪余量)。\n"
                "★ 60-90秒成片 ≈ 需要120-160秒源素材。\n\n"
                "规则:\n"
                "1. 跨时间选择（不按ASR顺序,按叙事逻辑）\n"
                "2. 优先选 importance≥4 的句子\n"
                "3. 同义句只选最精炼的一句\n"
                "4. 选3-8句,总源时长控制在目标时长的80-130%\n"
                "5. 选句需覆盖论点不同维度\n\n"
                "输出JSON: {\"sentences\":[{\"text\":\"原话\",\"source_start\":63.0,\"source_end\":67.0,\"reason\":\"为何选\"}]}",
                f"段落角色: {sec['role']}\n核心论点: {sec['point']}\n目标时长: ~{sec['duration']}s\n\n"
                f"采访ASR:\n{content_text[:5000]}",
                label=f"Step2-{i}",
            )
            sentences = result.get('sentences', [])
            for s in sentences:
                s['topic'] = sec['point'][:20]
                s['section_role'] = sec['role']
            all_selected.extend(sentences)
            time.sleep(0.3)

        # 合并去重
        seen = set()
        merged = []
        for s in all_selected:
            key = f"{s.get('source_start', 0):.0f}_{s['text'][:20]}"
            if key not in seen:
                seen.add(key)
                merged.append(s)

        # Step 3: 精细化
        print("[gen_script] Step 3: 精细化")
        script_preview = '\n'.join(
            f"[{i}] [{s.get('section_role', '?')}] {s['text'][:80]}"
            for i, s in enumerate(merged)
        )
        refinement = _call_llm(
            "你是短视频精编师。审核下面的脚本，完成三件事:\n\n"
            "1. 检查段落间是否有逻辑断裂，是否需要过渡句\n"
            "2. 检查是否有连续3句以上来自同一时间段（产生堆砌感）\n"
            "3. 在必要处补写过渡句(≤15字)，标注 source: 'ai_generated'\n"
            "   每段之间最多补1句，整片最多补3句\n\n"
            "输出JSON: {\"checks\":{\"logic_gaps\":[],\"rhythm_issues\":[]},"
            "\"bridges\":[{\"after_index\":2,\"text\":\"过渡句\",\"topic\":\"过渡\"}],"
            "\"notes\":\"其他建议\"}",
            f"脚本(按叙事顺序排列):\n{script_preview}",
            label="Step3",
        )

        # 组装 segments
        segments = []
        seg_id = 0
        bridges = refinement.get('bridges', [])
        bridge_map = {b['after_index']: b for b in bridges}

        for i, s in enumerate(merged):
            segments.append({
                "seg_id": seg_id,
                "highlight_text": s['text'],
                "source_start": s.get('source_start', 0),
                "source_end": s.get('source_end', s.get('source_start', 0) + 5),
                "topic": s.get('topic', ''),
                "section_role": s.get('section_role', ''),
                "edit_type": "trim",
                "narration_text": "",
                "note": s.get('reason', ''),
            })
            seg_id += 1
            if i in bridge_map:
                b = bridge_map[i]
                segments.append({
                    "seg_id": seg_id,
                    "highlight_text": b['text'],
                    "source_start": 0, "source_end": 0,
                    "topic": b.get('topic', '过渡'),
                    "section_role": "bridge",
                    "edit_type": "ai_generated",
                    "narration_text": "",
                    "note": "⚠️ AI补写,需人工配音或从素材补充",
                })
                seg_id += 1

        src_total = sum(
            (s.get('source_end', s.get('source_start', 0) + 3) - s.get('source_start', 0))
            for s in segments if s.get('edit_type') != 'ai_generated'
        )
        est_final = src_total * 0.5

        return {
            "ok": True,
            "topic": structure.get('topic', topic),
            "sections": structure.get('sections', []),
            "segments": segments,
            "checks": refinement.get('checks', {}),
            "bridges": bridges,
            "notes": refinement.get('notes', ''),
            "total": len(segments),
            "ai_generated_count": len(bridges),
            "time_estimate": {
                "budget": total_budget,
                "source_total": round(src_total, 1),
                "estimated_final": round(est_final, 1),
                "target": "60-90s",
                "status": "ok" if 50 <= est_final <= 110 else ("over" if est_final > 110 else "under"),
            },
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)[:200]}


# ── POST /script/generate_script_stream (v3 SSE) ──
def generate_script_stream(topic: str, emit_progress, emit_complete, emit_error):
    """v3 Agent 流水线 — SSE 流式"""
    from agents.script_agents import run_pipeline

    clean_dir = PROJECT_DIR / "sources_clean"
    classified_files = list(clean_dir.glob("classified_*.json"))
    classified = []
    if classified_files:
        classified = json.load(open(classified_files[0]))
    content = [s for s in classified if s.get('layer') == 'content']
    ctx = '\n'.join(
        f"[{s['start_sec']:.0f}s|{s.get('importance', 3)}] {s['text']}"
        for s in content
    )

    result = run_pipeline(topic, ctx, emit_progress=lambda step, msg, data=None:
        emit_progress(step, msg, data))

    if result.get('segments') and len(result['segments']) > 0:
        _save_segments(result, topic)
        _save_segments_task_level(result)
        emit_complete(result)
    else:
        emit_error(result.get('error', '生成失败: 未产出有效文案'),
                   str(result.get('edit_notes', ''))[:200])


# ── POST /script/generate_story_first (v4 SSE, 口播专用) ──
def generate_story_first(topic: str, emit_progress, emit_complete, emit_error):
    """v4 故事优先流水线 — SSE 流式"""
    from agents.script_agents import story_first_pipeline

    clean_dir = PROJECT_DIR / "sources_clean"
    enhanced_file = clean_dir / "classified_enhanced.json"
    if enhanced_file.exists():
        enhanced = json.load(open(enhanced_file))
        content = [s for s in enhanced
                   if s.get('speaker') == 'guest'
                   and s.get('layer') in ('content', 'guide')]
        ctx = '\n'.join(
            f"[{s['start_sec']:.0f}s|{s.get('importance', 3)}] {s.get('text', s.get('cleaned_text', ''))}"
            for s in content
        )
        emit_progress("story", f"📖 故事师: 加载{len(content)}句guest ASR (enhanced)...")
    else:
        classified_files = list(clean_dir.glob("classified_*.json"))
        classified = json.load(open(classified_files[0])) if classified_files else []
        content = [s for s in classified if s.get('layer') == 'content']
        ctx = '\n'.join(
            f"[{s['start_sec']:.0f}s|{s.get('importance', 3)}] {s['text']}"
            for s in content
        )
        emit_progress("story", f"📖 故事师: 加载{len(content)}句ASR...")

    result = story_first_pipeline(topic, ctx, emit_progress=lambda step, msg, data=None:
        emit_progress(step, msg, data))

    if result.get('segments') and len(result['segments']) > 0:
        _save_segments(result, topic, pipeline="story-first-v4")
        _save_segments_task_level(result)
        _sync_to_db(result)
        emit_complete(result)
    else:
        emit_error(result.get('error', '生成失败'))


# ── POST /script/refine (精切 SSE) ──
def refine_segments(task_name: str, emit_progress, emit_complete, emit_error):
    from cli.refine_segments import refine, load_data

    emit_progress("refine", "加载数据...")
    segs, utts = load_data(project_name, task_name)

    if not segs:
        emit_error("未找到粗剪 segments，请先生成脚本")
        return
    if not utts:
        emit_error("未找到 classified_enhanced 数据，请先运行数据管线")
        return

    emit_progress("refine", f"精切中... {len(segs)} 粗段, {len(utts)} 条标注")
    refined_segs = refine(segs, utts)

    seg_file = PROJECT_DIR / "tasks" / task_name / "segments.json"
    original = json.load(open(seg_file))
    original["segments"] = refined_segs
    original["refined"] = True

    n_keep = sum(s["refine_stats"]["keep"] for s in refined_segs)
    n_cut = sum(s["refine_stats"]["cut"] for s in refined_segs)
    keep_dur = sum(s["refine_stats"]["keep_duration"] for s in refined_segs)
    cut_dur = sum(s["refine_stats"]["cut_duration"] for s in refined_segs)
    original["refine_summary"] = {
        "total_sub_clips": n_keep + n_cut,
        "keep": n_keep, "cut": n_cut,
        "keep_duration": round(keep_dur, 1),
        "cut_duration": round(cut_dur, 1),
        "cut_pct": round(cut_dur / max(keep_dur + cut_dur, 1) * 100, 0),
    }

    json.dump(original, open(seg_file, "w"), ensure_ascii=False, indent=2)

    emit_complete({
        "ok": True,
        "summary": original["refine_summary"],
        "msg": f"精切完成: {n_keep} 保留 + {n_cut} 删除 ({cut_dur:.0f}s 废料)",
        "segments": refined_segs,
    })
    print(f"[refine] 精切完成: {n_keep}K + {n_cut}C → {seg_file}")


# ── 辅助函数 ──
def _save_segments(result, topic, pipeline="v3"):
    """保存文案脚本到项目级 tasks/ 目录"""
    tasks_dir = PROJECT_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    script_file = tasks_dir / "文案脚本.json"
    save_data = {
        "topic": result.get("topic", topic),
        "sections": result.get("sections", []),
        "segments": result["segments"],
        "total": result.get("total", len(result["segments"])),
        "time_estimate": result.get("time_estimate", {}),
    }
    if pipeline == "story-first-v4":
        save_data["story"] = result.get("story", "")
        save_data["pipeline"] = "story-first-v4"
    else:
        save_data["review_issues"] = result.get("review_issues", [])
        save_data["review_verdict"] = result.get("review_verdict", "?")
    json.dump(save_data, open(script_file, "w"), ensure_ascii=False, indent=2)
    result["script_file"] = str(script_file)
    result["script_file_url"] = "/tasks/文案脚本.json"


def _save_segments_task_level(result):
    """同步写入任务级 segments.json"""
    tasks_dir = PROJECT_DIR / "tasks"
    task_dir = tasks_dir / (args.task or "default")
    task_dir.mkdir(parents=True, exist_ok=True)
    seg_file = task_dir / "segments.json"

    hook_line = ""
    closing_line = ""
    for s in result["segments"]:
        t = s.get("topic", "")
        if ("hook" in t.lower() or "开场" in t) and not hook_line:
            hook_line = s.get("highlight_text", "")
        if ("收尾" in t or "洞察" in t or "closing" in t.lower()) and not closing_line:
            closing_line = s.get("highlight_text", "")

    seg_data = {
        "task_type": "interview",
        "source": result.get("source", "学习新东方"),
        "total_segments": len(result["segments"]),
        "target_duration": result.get("time_estimate", {}).get("target", "~60s"),
        "hook_line": hook_line,
        "closing_line": closing_line,
        "audio_verified": False,
        "segments": result["segments"],
    }
    json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)
    print(f"[pipeline] segments.json 已同步到任务目录: {seg_file}")


def _sync_to_db(result):
    """同步写入 SQLite"""
    try:
        drama_id = db.get_drama_id(project_name)
        if drama_id:
            task_name = args.task or f"story_{int(time.time())}"
            existing = db.get_task(drama_id, task_name)
            if existing:
                task_id = existing["id"]
                db.save_task_segments(task_id, result["segments"])
            else:
                task_id = db.create_task(drama_id, task_name)
                db.save_task_segments(task_id, result["segments"])
            print(f"[story-first] DB: task={task_name} task_id={task_id} segs={len(result['segments'])}")
            result["task_id"] = task_id
    except Exception as e:
        print(f"[story-first] DB save failed (non-critical): {e}")
