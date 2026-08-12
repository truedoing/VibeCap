"""
编剧 Agent 系统 — 电视剧解说脚本生成

四个独立 Agent 角色，通过编排器 run_drama_pipeline() 协调。

Agent 协议:
  输入: 结构化数据 (story_map / chapter_plan / scene_data)
  输出: {"ok": True, "result": {...}} | {"ok": False, "error": "..."}

对标 script_agents.py 的 Agent 模式，但：
  - 口播 Agent 是"选句"（从 ASR 挑原话）
  - 编剧 Agent 是"创作"（写旁白 + 生成 scene_query）
"""

import json
import re
import time
from pathlib import Path

from lib.llm import call_deepseek_json, call_deepseek
from lib.vlm_cache import KNOWN_CHARACTERS, get_char_counts

# ── Prompt 模板 ──
from handlers.prompts.script_drama import (
    STORY_MASTER_PROMPT,
    NARRATIVE_PLANNER_PROMPT,
    SCRIPT_WRITER_PROMPT,
    REVIEWER_PROMPT,
)


def _call_llm(system_prompt, user_content, temp=0.4, max_tokens=4000, timeout=180, label="agent"):
    """底层 LLM 调用 — 兼容 script_agents.py 的协议"""
    result = call_deepseek_json(
        system_prompt, user_content,
        temperature=temp, max_tokens=max_tokens,
        timeout=timeout, retries=3, label=label,
    )
    if result["ok"]:
        data = result["data"]
        if isinstance(data, list):
            data = {"items": data}
        return {"ok": True, "result": data}
    return {"ok": False, "error": result.get("error", "?")[:200]}


# ═══════════════════════════════════════════════════════════════
# 数据加载辅助函数
# ═══════════════════════════════════════════════════════════════

def _load_all_synopses(project_dir: Path) -> dict:
    """加载全部剧集的剧情概要 → {ep: synopsis_text}"""
    synopses = {}
    sources = project_dir / "sources"
    if not sources.exists():
        return synopses

    for ep_dir in sorted(sources.iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        try:
            ep = int(ep_dir.name[2:])
        except ValueError:
            continue
        syn_file = ep_dir / "ep_synopsis.json"
        if syn_file.exists():
            data = json.load(open(syn_file))
            synopses[ep] = data.get("synopsis", "")
    return synopses


def _load_scene_maps(project_dir: Path, episodes: list[int]) -> dict:
    """加载指定剧集的 scene_map → {ep: [scene_dict, ...]}"""
    scene_maps = {}
    sources = project_dir / "sources"
    for ep in episodes:
        sm_file = sources / f"ep{ep}" / "scene_map.json"
        if not sm_file.exists():
            sm_file = sources / f"ep{ep:02d}" / "scene_map.json"
        if sm_file.exists():
            scene_maps[ep] = json.load(open(sm_file))
    return scene_maps


def _load_vlm_descriptions(project_dir: Path, episodes: list[int]) -> dict:
    """加载 VLM 描述（可选，用于增强写作上下文）→ {ep: {scene_idx: vlm_data}}"""
    vlm = {}
    sources = project_dir / "sources"
    for ep in episodes:
        vlm_file = sources / f"ep{ep}" / "vlm_seg_cache_v3.json"
        if not vlm_file.exists():
            vlm_file = sources / f"ep{ep:02d}" / "vlm_seg_cache_v3.json"
        if vlm_file.exists():
            vlm[ep] = json.load(open(vlm_file))
    return vlm


def _format_synopses_text(synopses: dict) -> str:
    """将全部剧集概要格式化为 LLM 输入文本"""
    lines = []
    for ep in sorted(synopses.keys()):
        text = synopses[ep]
        # 清理 markdown 格式
        text = re.sub(r'\*\*|#{1,4}\s*', '', text)
        lines.append(f"═══ 第{ep}集 ═══\n{text[:600]}")
    return '\n\n'.join(lines)


def _format_scene_map_text(scene_map: list, ep: int) -> str:
    """将单集 scene_map 格式化为 LLM 输入文本"""
    lines = [f"═══ 第{ep}集 场景分段 ═══"]
    for i, sm in enumerate(scene_map):
        chars = '、'.join(sm.get('characters', []))
        time_str = f"{sm['time_range'][0]}s-{sm['time_range'][1]}s"
        lines.append(
            f"[场景{i}] {time_str} | 📍{sm.get('location', '?')} | "
            f"👤{chars} | 事件:{sm.get('event', '?')} | 情绪:{sm.get('mood', '?')}"
        )
    return '\n'.join(lines)


def _build_char_summary() -> str:
    """构建角色统计文本"""
    counts = get_char_counts()
    if not counts:
        counts = {c: 0 for c in KNOWN_CHARACTERS}
    items = sorted(counts.items(), key=lambda x: -x[1])
    return '、'.join(f"{c}({cnt}场)" for c, cnt in items)


# ═══════════════════════════════════════════════════════════════
# Agent 1: 故事师 — 通读全部剧集概要，提取故事地图
# ═══════════════════════════════════════════════════════════════

def story_master_agent(project_dir: Path, drama_name: str,
                       focus_episodes: list[int] = None) -> dict:
    """输入: 全部剧集概要 → 输出: story_map

    如果指定 focus_episodes，额外加载对应 scene_map 辅助分析。
    """
    # 加载数据
    synopses = _load_all_synopses(project_dir)
    if not synopses:
        return {"ok": False, "error": f"未找到任何剧集概要数据 (sources/ep*/ep_synopsis.json)"}

    syn_text = _format_synopses_text(synopses)

    # 可选：加载焦点剧集的 scene_map 辅助
    if focus_episodes:
        scene_maps = _load_scene_maps(project_dir, focus_episodes)
        scene_context = '\n\n'.join(
            _format_scene_map_text(sm, ep) for ep, sm in sorted(scene_maps.items())
        )
        scene_note = f"\n\n★★ 以下是用户关注的剧集的详细场景分段（辅助分析）：\n{scene_context[:8000]}"
    else:
        scene_note = ""

    episode_constraint = ""
    if focus_episodes:
        ep_list = '、'.join(str(e) for e in sorted(focus_episodes))
        episode_constraint = f"\n★ 用户当前关注剧集: 第{ep_list}集。请在 highlight_scenes 和 topic_suggestions 中优先覆盖这些剧集。"

    system = STORY_MASTER_PROMPT.format(
        drama_name=drama_name,
        known_characters='、'.join(KNOWN_CHARACTERS),
        episode_constraint=episode_constraint,
    )

    user = (
        f"★★ 全部剧集剧情概要 (共{len(synopses)}集):\n\n"
        f"{syn_text}"
        f"{scene_note}"
    )

    return _call_llm(system, user, temp=0.3, max_tokens=8000, timeout=300, label="story_master")


# ═══════════════════════════════════════════════════════════════
# Agent 2: 策划师 — 设计叙事结构和章节规划
# ═══════════════════════════════════════════════════════════════

def narrative_planner_agent(story_map: dict, user_topic: str,
                            target_duration: int = 480) -> dict:
    """输入: story_map + 用户选题 → 输出: chapter_structure"""
    # 提取角色列表
    char_arcs = story_map.get('character_arcs', [])
    main_char_names = [a['name'] for a in char_arcs[:5]] if char_arcs else KNOWN_CHARACTERS

    # 构建章节数建议
    suggested_chapters = max(4, min(7, target_duration // 80))

    system = NARRATIVE_PLANNER_PROMPT

    user = (
        f"故事地图:\n{json.dumps(story_map, ensure_ascii=False, indent=2)[:8000]}\n\n"
        f"★★ 用户选题: {user_topic}\n"
        f"★★ 目标时长: {target_duration}秒 (约{target_duration//60}分钟)\n"
        f"★★ 建议章节数: {suggested_chapters}章\n"
        f"★★ 主要角色: {', '.join(main_char_names)}\n\n"
        f"请设计叙事方案。"
    )

    return _call_llm(system, user, temp=0.5, max_tokens=3000, label="narrative_planner")


# ═══════════════════════════════════════════════════════════════
# Agent 3: 文案师 — 逐章写作解说词 + scene_query
# ═══════════════════════════════════════════════════════════════

def script_writer_agent(chapter: dict, scene_maps: dict,
                        prev_chapter_summary: str = "",
                        next_chapter_summary: str = "") -> dict:
    """输入: 单个章节方案 + scene_map 数据 → 输出: segments 数组

    Args:
      chapter: 章节方案 dict (从策划师输出)
      scene_maps: {ep: [scene_dict, ...]} 覆盖章节涉及的剧集
      prev_chapter_summary: 前一章摘要 (用于过渡)
      next_chapter_summary: 后一章摘要 (用于过渡)
    """
    # 收集本章涉及剧集的 scene_map
    focus_eps = chapter.get('episodes_focus', [])
    if isinstance(focus_eps, int):
        focus_eps = [focus_eps]

    scene_context_parts = []
    for ep in focus_eps:
        if ep in scene_maps:
            scene_context_parts.append(_format_scene_map_text(scene_maps[ep], ep))

    # 如果 scene_maps 没有聚焦剧集的数据，使用所有已加载的
    if not scene_context_parts:
        for ep, sm in sorted(scene_maps.items()):
            scene_context_parts.append(_format_scene_map_text(sm, ep))

    scene_context = '\n\n'.join(scene_context_parts) if scene_context_parts else "(无场景数据)"

    # 过渡上下文
    transition_context = ""
    if prev_chapter_summary:
        transition_context += f"\n前一章摘要 (用于过渡衔接): {prev_chapter_summary}"
    if next_chapter_summary:
        transition_context += f"\n后一章摘要 (用于过渡衔接): {next_chapter_summary}"

    system = SCRIPT_WRITER_PROMPT.format(
        known_characters='、'.join(KNOWN_CHARACTERS),
    )

    user = (
        f"★★ 当前章节方案:\n{json.dumps(chapter, ensure_ascii=False, indent=2)}\n\n"
        f"★★ 场景数据 (scene_map):\n{scene_context}"
        f"{transition_context}\n\n"
        f"请为本章撰写解说词。"
    )

    return _call_llm(system, user, temp=0.6, max_tokens=3000, label="script_writer")


# ═══════════════════════════════════════════════════════════════
# Agent 4: 审核师 — 剧情准确性 + 情绪曲线 + 节奏审核
# ═══════════════════════════════════════════════════════════════

def reviewer_agent(segments: list, scene_maps: dict,
                   target_duration: int = 480) -> dict:
    """输入: 完整脚本 + scene_map 数据 → 输出: 审核报告 + 修正建议"""
    # 构建 scene_map 参考文本 (用于事实核查)
    scene_ref_parts = []
    for ep, sm in sorted(scene_maps.items()):
        scene_ref_parts.append(_format_scene_map_text(sm, ep))
    scene_ref = '\n\n'.join(scene_ref_parts)

    # 构建脚本预览
    script_preview_lines = []
    total_chars = 0
    for i, seg in enumerate(segments):
        narr = seg.get('narration_text', '')
        total_chars += len(narr)
        sq = seg.get('scene_query', {})
        sq_summary = ""
        if sq and sq.get('episode'):
            sq_summary = f" [EP{sq['episode']} {sq.get('event', '?')[:20]}]"
        script_preview_lines.append(
            f"[S{i}] {narr[:60]}...{sq_summary}"
        )

    est_duration = total_chars / 4  # 4字/秒
    script_preview = '\n'.join(script_preview_lines)

    system = REVIEWER_PROMPT

    user = (
        f"★★ 目标时长: {target_duration}秒\n"
        f"★★ 当前总字数: {total_chars}字, 预估配音时长: {est_duration:.0f}秒\n\n"
        f"★★ 完整脚本 ({len(segments)}段):\n{script_preview}\n\n"
        f"★★ 脚本详细数据:\n{json.dumps(segments, ensure_ascii=False, indent=2)[:3000]}\n\n"
        f"★★ ★ 全量场景数据 (用于事实核查，请逐段对照):\n{scene_ref}"
    )

    return _call_llm(system, user, temp=0.3, max_tokens=3000, label="reviewer")


def apply_fixes(segments: list, review_result: dict) -> tuple:
    """应用审核修正 → (fixed_segments, fix_count)

    优先使用审核师在 fixed_segments 中提供的修正版本。
    对于没有提供修正版本的 issue，如果 severity=high 则标记 note。
    """
    fixes = review_result.get('fixed_segments', [])
    if not fixes:
        return segments, 0

    fix_map = {}
    for f in fixes:
        idx = f.get('segment_index', -1)
        if 0 <= idx < len(segments):
            fix_map[idx] = f

    fixed = []
    applied = 0
    for i, seg in enumerate(segments):
        if i in fix_map:
            f = fix_map[i]
            seg = dict(seg)
            if f.get('narration_text'):
                seg['narration_text'] = f['narration_text']
            if f.get('scene_query'):
                seg['scene_query'] = f['scene_query']
            seg['note'] = (seg.get('note', '') + f" | 审核修正: {f.get('fix_reason', '')}").strip(' |')
            applied += 1
        fixed.append(seg)

    return fixed, applied


# ═══════════════════════════════════════════════════════════════
# 编排器: 协调四个 Agent 完成完整流程
# ═══════════════════════════════════════════════════════════════

def run_drama_pipeline(
    project_dir: Path,
    topic: str,
    *,
    drama_name: str = "都挺好",
    focus_episodes: list[int] = None,
    target_duration: int = 480,
    emit_progress=None,
) -> dict:
    """完整编剧流水线 — 四个 Agent 协作生成解说脚本

    Args:
      project_dir: 项目数据目录
      topic: 用户选题 (如"苏明成人物线 8分钟解说")
      drama_name: 剧名
      focus_episodes: 关注的剧集范围 (可选，不指定则分析全部)
      target_duration: 目标时长 (秒)
      emit_progress: 进度回调 fn(step, msg, data=None)

    Returns:
      {"ok": True, "segments": [...], "cover": "...", "story_map": {...}, ...}
    """
    def progress(step, msg, data=None):
        if emit_progress:
            emit_progress(step, msg, data)

    # ── Phase 1: 故事师 ──
    progress("story", "📖 故事师: 通读全部剧情概要，提取故事地图...")
    start = time.time()
    story_result = story_master_agent(project_dir, drama_name, focus_episodes)

    if not story_result.get('ok'):
        return {"ok": False, "error": f"故事师失败: {story_result.get('error', '?')}"}

    story_map = story_result['result']
    elapsed = time.time() - start
    char_count = len(story_map.get('character_arcs', []))
    topic_count = len(story_map.get('topic_suggestions', []))
    progress("story_done",
        f"✅ 故事地图: {char_count}个人物弧光 · {len(story_map.get('turning_points', []))}个转折点 · {topic_count}个选题 · {elapsed:.0f}s",
        {"story_map": story_map})

    # ── Phase 2: 策划师 ──
    progress("planning", "📐 策划师: 设计叙事结构和章节规划...")
    start = time.time()
    plan_result = narrative_planner_agent(story_map, topic, target_duration)

    if not plan_result.get('ok'):
        return {"ok": False, "error": f"策划师失败: {plan_result.get('error', '?')}"}

    chapter_structure = plan_result['result']
    chapters = chapter_structure.get('chapters', [])
    elapsed = time.time() - start

    if not chapters:
        return {"ok": False, "error": "策划师未产出章节方案"}

    progress("planning_done",
        f"✅ 叙事方案: {chapter_structure.get('title', '?')} · {len(chapters)}章 · 目标{target_duration}s",
        {"chapter_structure": chapter_structure})

    # ── 准备 scene_map 数据 (供文案师和审核师共享) ──
    # 只加载用户指定剧集范围内的 scene_map — 不加载全量46集
    all_eps = set()
    for ch in chapters:
        eps = ch.get('episodes_focus', [])
        if isinstance(eps, int):
            eps = [eps]
        all_eps.update(eps)
    if focus_episodes:
        all_eps.update(focus_episodes)
    # 扩展邻近集 (±2集, 用于过渡)
    expanded_eps = set()
    for ep in all_eps:
        for e in range(max(1, ep-2), min(47, ep+3)):
            expanded_eps.add(e)
    scene_maps = _load_scene_maps(project_dir, sorted(expanded_eps))

    # ── Phase 3: 文案师 (逐章写作) ──
    progress("writing", f"✍️ 文案师: 逐章写作解说词 (共{len(chapters)}章)...")
    all_segments = []
    chapter_summaries = []

    for i, chapter in enumerate(chapters):
        ch_title = chapter.get('title', f'第{i+1}章')
        progress("writing", f"  写作第{i+1}/{len(chapters)}章: {ch_title}...",
                 {"chapter": i+1, "total": len(chapters)})

        prev_summary = chapter_summaries[-1] if chapter_summaries else ""
        next_summary = ""  # 后续章节的标题作为轻量上下文

        write_result = script_writer_agent(
            chapter, scene_maps,
            prev_chapter_summary=prev_summary,
            next_chapter_summary=next_summary,
        )

        if not write_result.get('ok'):
            progress("writing", f"  ⚠️ 第{i+1}章写作失败: {write_result.get('error', '?')}")
            continue

        chapter_segments = write_result['result'].get('segments', [])
        if not chapter_segments:
            progress("writing", f"  ⚠️ 第{i+1}章未产出有效段落")
            continue

        # 注入章节元数据
        for seg in chapter_segments:
            seg['chapter_title'] = ch_title
            seg['chapter_idx'] = i
            seg['section_role'] = chapter.get('narrative_function', 'context')

        # 提取文案师产的 cover 字段
        if i == 0:
            first_cover = write_result['result'].get('cover', '')
            if first_cover:
                chapter_segments[0]['_cover'] = first_cover

        all_segments.extend(chapter_segments)
        chapter_summaries.append(f"[{ch_title}] {chapter.get('narrative_goal', '')[:60]}")

        progress("writing_chapter_done",
            f"  ✅ 第{i+1}章 {ch_title}: {len(chapter_segments)}段",
            {"chapter": i+1, "segments": len(chapter_segments)})

        time.sleep(0.5)  # 避免 API 限流

    if not all_segments:
        return {"ok": False, "error": "文案师未产出任何有效章节"}

    # 统一分配 seg_id
    for i, seg in enumerate(all_segments):
        seg['seg_id'] = i

    total_chars = sum(len(s.get('narration_text', '')) for s in all_segments)
    est_duration = total_chars / 4
    progress("writing_done",
        f"✅ 文案完成: {len(all_segments)}段 · {total_chars}字 · 预估{est_duration:.0f}s",
        {"total_segments": len(all_segments), "total_chars": total_chars,
         "est_duration": round(est_duration, 1)})

    # ── Phase 4: 后处理 (校验 + 补漏 + episode_marker) ──
    progress("verify", "🔍 校验 scene_query + 填充 episode_marker...")

    # 程序级验证：逐个 segment 检查 scene_query 是否匹配 scene_map
    verified = []
    fixed = 0
    for seg in all_segments:
        sq = seg.get('scene_query', {})
        if sq is None:
            sq = {}
            seg['scene_query'] = sq
        if not isinstance(sq, dict):
            sq = {}
            seg['scene_query'] = sq
        ep = sq.get('episode')
        tr = sq.get('time_range')

        # 填充 episode_marker 和 source_start/source_end (兼容前端显示)
        if ep and tr and isinstance(tr, list) and len(tr) == 2:
            seg['episode_marker'] = {
                "episode": ep,
                "approx_minute": tr[0] / 60.0,
                "raw": f"{ep}~{tr[0]//60:.0f}m{tr[0]%60:.0f}s",
            }
            seg['source_start'] = float(tr[0])
            seg['source_end'] = float(tr[1])
            seg['video_episode'] = ep
        else:
            seg['episode_marker'] = None
            seg['mode'] = 'C'

        if not ep:
            # 没有 scene_query — 自动转为 mode C
            seg['mode'] = 'C'
            verified.append(seg)
            continue

        sm_list = scene_maps.get(ep, [])
        if not sm_list:
            # scene_map 不存在 — 降级为 mode C
            sq['episode'] = None
            sq['time_range'] = None
            sq['event'] = sq.get('event', '') + ' (scene_map缺失)'
            seg['mode'] = 'C'
            fixed += 1
            verified.append(seg)
            continue

        # 精确匹配 time_range
        matched = [s for s in sm_list if s['time_range'] == tr]
        if matched:
            sm_entry = matched[0]
            # 用 scene_map 的 event/mood 覆盖（确保一致）
            sq['event'] = sm_entry.get('event', sq.get('event', ''))
            sq['mood'] = sm_entry.get('mood', sq.get('mood', ''))
            sq['location'] = sm_entry.get('location', sq.get('location', ''))
            sq['characters'] = sm_entry.get('characters', sq.get('characters', []))
            verified.append(seg)
        else:
            # 找最近匹配
            closest = min(sm_list, key=lambda s: abs(s['time_range'][0] - tr[0]))
            gap = abs(closest['time_range'][0] - tr[0])
            if gap <= 15:
                # 修正 time_range
                sq['time_range'] = closest['time_range']
                sq['event'] = closest.get('event', sq.get('event', ''))
                sq['mood'] = closest.get('mood', sq.get('mood', ''))
                sq['location'] = closest.get('location', sq.get('location', ''))
                sq['characters'] = closest.get('characters', sq.get('characters', []))
                fixed += 1
                verified.append(seg)
            else:
                # 找不到匹配 — 降级
                sq['episode'] = None
                sq['time_range'] = None
                sq['event'] = sq.get('event', '') + f' (无匹配,最近:EP{ep}{closest["time_range"]})'
                seg['mode'] = 'C'
                fixed += 1
                verified.append(seg)

    progress("verify_done",
        f"✅ 校验完成: {len(all_segments)}段, 修正{fixed}处, 0个LLM审核",
        {"verified": len(all_segments), "fixed": fixed})

    # ── 提取 cover（封面钩子 — 由文案师写） ──
    cover = ''
    # 文案师输出的 cover 字段
    if all_segments:
        first = all_segments[0]
        # 优先用文案师指定的 cover，其次用 narration_text 的前2句
        cover = first.pop('_cover', '')
        if not cover:
            narr = first.get('narration_text', '')
            # 取前两句话作为封面钩子
            sentences = narr.replace('？','。').replace('！','。').split('。')
            cover = '。'.join(sentences[:2]) + '。' if len(sentences) > 1 else narr[:40]
            cover = cover[:60]  # 截断到60字
    if not cover:
        cover = chapter_structure.get('title', '')

    # ── 组装最终输出 ──
    # episode_marker 已在 Phase 4 中填充，这里做兜底

    return {
        "ok": True,
        "pipeline": "drama-agent-v1",
        "topic": topic,
        "cover": cover,
        "story_map": story_map,
        "chapter_structure": chapter_structure,
        "segments": all_segments,
        "total": len(all_segments),
        "total_chars": total_chars,
        "review": {"verdict": "verified", "issues": [], "fixed": fixed},
        "review_verdict": "verified",
        "review_issues": [],
        "time_estimate": {
            "target": target_duration,
            "total_chars": total_chars,
            "estimated_sec": round(est_duration, 1),
            "estimated_min": f"{est_duration/60:.1f}分钟",
            "status": "ok" if abs(est_duration - target_duration) < target_duration * 0.4 else (
                "over" if est_duration > target_duration else "under"),
        },
    }
