"""配音台 SSE 处理函数 — POST /voiceover/generate_stream

配音师 Agent 协议:
  输入: segments 脚本 (narration_text + section_role)
  输出: 配音方案 (emotion + speed + pause_after_ms) → 逐段 TTS 生成

对标 handlers/script_drama.py 的模式:
  generate_voiceover() 作为 SSE 回调函数
  负责加载数据 → 配音师Agent设计方案 → 逐段TTS生成 → 保存结果 → 发送 SSE 事件
"""

import json
import os
import subprocess
import time
from pathlib import Path

from config import project_name, PROJECT_DIR, BASE_DIR, args
from config import resolve_work_dir
from db import VibeCutDB

DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


def resolve_tts_dir(task_name: str = None) -> Path:
    """TTs 音频输出目录"""
    return resolve_work_dir(task_name) / "tts_segments"


def generate_voiceover(
    task_name: str,
    voice: str,
    speed: float,
    pause_ms: int,
    ref_audio_path: str | None,
    emit_progress,
    emit_complete,
    emit_error,
):
    """配音台 SSE 主流程

    流程:
      1. 加载 segments.json
      2. 配音师 Agent 设计配音方案 (LLM)
      3. 逐段 TTS 生成 (MiMo API)
      4. 保存 narration.json + tts_meta.json
    """
    from tts_engine import generate_speech, PRESET_VOICES
    from lib.llm import call_deepseek_json

    task_dir = resolve_work_dir(task_name).parent
    seg_file = task_dir / "segments.json"
    if not seg_file.exists():
        seg_file = PROJECT_DIR / "tasks" / "segments.json"
    if not seg_file.exists():
        seg_file = PROJECT_DIR / "tasks" / "文案脚本.json"
    if not seg_file.exists():
        emit_error("未找到脚本文件", "请先在编剧台生成解说脚本")
        return

    data = json.load(open(seg_file))
    segments = data.get("segments", [])
    if not segments:
        emit_error("脚本为空", "segments 数组为空")
        return

    # 提取有 narration_text 的段
    narr_segments = []
    skip_count = 0
    for seg in segments:
        narr = (seg.get("narration_text") or "").strip()
        if narr:
            narr_segments.append({
                "seg_id": seg.get("seg_id", len(narr_segments)),
                "narration_text": narr,
                "section_role": seg.get("section_role", "context"),
                "chapter_title": seg.get("chapter_title", ""),
            })
        else:
            skip_count += 1

    if not narr_segments:
        emit_error("脚本无解说词", f"{len(segments)}段中无narration_text，请用drama模式生成")
        return

    emit_progress("init",
        f"🎙️ 配音师就绪 · {len(narr_segments)}段解说词 · 音色: {PRESET_VOICES.get(voice, {}).get('label', voice)}",
        {"total": len(narr_segments), "skip": skip_count, "voice": voice, "speed": speed})

    # ── Phase 1: 配音师 Agent ──
    emit_progress("director", "🎬 配音师分析脚本 → 设计配音方案...")

    voice_plan = _run_voice_director(narr_segments, call_deepseek_json, emit_progress)

    if not voice_plan:
        # Fallback: 无 LLM 时的默认方案
        emit_progress("director", "⚠️ 配音师不可用，使用默认方案 (规则驱动)")
        voice_plan = _default_voice_plan(narr_segments, speed, pause_ms)
    else:
        emit_progress("director_done",
            f"✅ 配音方案就绪: {len(voice_plan)}段 · 风格: {voice_plan[0].get('_overall_style', '')}",
            {"plan_segments": len(voice_plan)})

    # ── Phase 2: 逐段 TTS 生成 ──
    tts_dir = resolve_tts_dir(task_name)
    tts_dir.mkdir(parents=True, exist_ok=True)

    tts_results = []
    total_duration = 0.0
    current_time = 0.0

    for i, plan in enumerate(voice_plan):
        seg_id = plan.get("seg_id", i)
        text = plan.get("narration_text", "")

        # 找到原始 segment 的完整数据
        orig = next((s for s in narr_segments if s.get("seg_id") == seg_id), None)
        if not orig:
            continue

        out_path = tts_dir / f"narr_{i:03d}.wav"

        seg_emotion = plan.get("emotion", "narrative")
        seg_speed = plan.get("speed", speed)
        seg_pause = plan.get("pause_after_ms", pause_ms)
        emphasize = plan.get("emphasize", [])

        # 构建 style_hint
        emotion_hints = {
            "suspense": "压低声音，制造悬念感，语气神秘",
            "narrative": "平稳叙述，咬字清晰，自然流畅",
            "passionate": "声音饱满有力，情绪激昂，富有感染力",
            "analytical": "冷静克制，语气理性，有说服力",
            "warm": "温暖柔和，娓娓道来，有治愈感",
            "humorous": "语气轻快，带一点调侃感，自然不刻意",
        }
        style = emotion_hints.get(seg_emotion, "自然叙述")
        if emphasize:
            style += f"，重读词语: {'、'.join(emphasize)}"

        emit_progress("segment_start",
            f"  🎤 [{i+1}/{len(voice_plan)}] {seg_emotion} | {text[:40]}...",
            {"seg_id": seg_id, "index": i, "emotion": seg_emotion, "speed": seg_speed})

        result = generate_speech(
            text, str(out_path),
            voice=voice,
            speed=seg_speed,
            ref_audio_path=ref_audio_path,
            style_hint=style,
        )

        if result["ok"]:
            duration = round(result["duration"], 2)

            tts_results.append({
                "index": i,
                "seg_id": seg_id,
                "start": round(current_time, 2),
                "end": round(current_time + duration, 2),
                "narration": text,
                "narration_text": text,
                "audio_path": f"tts_segments/narr_{i:03d}.wav",
                "duration": duration,
                "pause_after_ms": seg_pause,
                "overlaps_speech": False,
                "emotion": seg_emotion,
                "speed": seg_speed,
            })

            current_time += duration + (seg_pause / 1000.0)
            total_duration += duration

            emit_progress("segment_done",
                f"  ✅ [{i+1}/{len(voice_plan)}] {duration:.1f}s | {text[:30]}...",
                {"seg_id": seg_id, "index": i, "duration": duration,
                 "done": i + 1, "total": len(voice_plan)})
        else:
            emit_progress("segment_error",
                f"  ❌ [{i+1}/{len(voice_plan)}] 生成失败: {result.get('error', '?')[:60]}",
                {"seg_id": seg_id, "index": i, "error": result.get("error", "")})

        time.sleep(0.3)  # 避免 API 限流

    if not tts_results:
        emit_error("全部段落生成失败", "请检查 MIMO_API_KEY 和网络连接")
        return

    # ── Phase 3: 保存产物 ──
    _save_results(task_dir, tts_results, voice, speed, pause_ms, emit_progress)

    emit_complete({
        "ok": True,
        "engine": "mimo-v2.5-tts",
        "total_segments": len(tts_results),
        "total_duration": round(total_duration, 1),
        "voice": voice,
        "tts_dir": str(tts_dir),
        "tts_meta_path": str(task_dir / "tts_meta.json"),
        "narration_path": str(task_dir / "narration.json"),
    })


# ═══════════════════════════════════════════════════════════════
# 配音师 Agent
# ═══════════════════════════════════════════════════════════════

def _run_voice_director(narr_segments: list, call_llm_json, emit_progress) -> list | None:
    """配音师 Agent: 理解脚本叙事结构，为每段设计配音方案

    Args:
        narr_segments: [{"seg_id", "narration_text", "section_role", "chapter_title"}, ...]
        call_llm_json: DeepSeek JSON 调用函数

    Returns:
        voice_plan list 或 None (LLM 不可用时 fallback 到规则)
    """
    from handlers.prompts.voiceover import VOICE_DIRECTOR_PROMPT

    # 精简每条 segment，控制 token
    script_preview = []
    for s in narr_segments:
        script_preview.append({
            "seg_id": s["seg_id"],
            "narration_text": s["narration_text"],
            "section_role": s.get("section_role", "context"),
        })

    target_duration = 240  # 默认4分钟
    total_chars = sum(len(s["narration_text"]) for s in narr_segments)
    est_duration = total_chars / 3.5  # 中文 TTS ~3.5字/秒

    user_content = (
        f"★ 解说脚本 ({len(narr_segments)}段, 共{total_chars}字, 预估{est_duration:.0f}秒):\n"
        f"{json.dumps(script_preview, ensure_ascii=False, indent=2)}\n\n"
        f"★ 目标时长: {target_duration}秒\n"
        f"请为每段设计配音方案。"
    )

    try:
        result = call_llm_json(
            VOICE_DIRECTOR_PROMPT,
            user_content,
            temperature=0.4,
            max_tokens=2000,
            timeout=60,
            retries=2,
            label="voice_director",
        )
    except Exception as e:
        emit_progress("director", f"⚠️ 配音师调用失败: {str(e)[:80]}")
        return None

    if not result.get("ok"):
        emit_progress("director", f"⚠️ 配音师返回异常: {result.get('error', '?')[:80]}")
        return None

    data = result.get("data", {})
    if isinstance(data, list):
        data = {"plan": data}

    plan = data.get("plan", [])
    overall_style = data.get("overall_style", "")

    # 合并 narration_text 到 plan (LLM 不返回文本，只有参数)
    enriched = []
    for p in plan:
        seg_id = p.get("seg_id", len(enriched))
        orig = next((s for s in narr_segments if s.get("seg_id") == seg_id), None)
        if orig is None:
            orig = narr_segments[seg_id] if seg_id < len(narr_segments) else None
        if orig:
            p["narration_text"] = orig.get("narration_text", "")
            p["chapter_title"] = orig.get("chapter_title", "")
        p["_overall_style"] = overall_style
        enriched.append(p)

    return enriched if enriched else None


def _default_voice_plan(narr_segments: list, global_speed: float, global_pause: int) -> list:
    """规则驱动的默认配音方案 (配音师 Agent 不可用时的 fallback)

    基于 section_role 匹配情绪和语速，无需 LLM。
    """
    role_map = {
        "hook_tension": ("suspense", 0.9, 500),
        "evidence":      ("passionate", 0.95, 350),
        "context":       ("narrative", 1.0, 300),
        "bridge":        ("narrative", 1.0, 300),
        "insight":       ("analytical", 0.95, 400),
        "closing":       ("warm", 0.85, 600),
        "highlight":     ("passionate", 0.9, 400),
    }
    default = ("narrative", 1.0, 300)

    plan = []
    for s in narr_segments:
        role = s.get("section_role", "context")
        emotion, spd, pause = role_map.get(role, default)

        # 全局 speed 作为倍率叠加
        spd = round(spd * global_speed, 2)

        plan.append({
            "seg_id": s["seg_id"],
            "narration_text": s["narration_text"],
            "chapter_title": s.get("chapter_title", ""),
            "emotion": emotion,
            "speed": min(1.5, max(0.7, spd)),
            "pause_after_ms": pause if pause == global_pause else max(0, min(2000, pause)),
            "emphasize": [],
            "reason": f"规则匹配: {role} → {emotion}",
            "_overall_style": "规则驱动默认方案",
        })

    return plan


# ═══════════════════════════════════════════════════════════════
# 产物保存
# ═══════════════════════════════════════════════════════════════

def _save_results(task_dir: Path, tts_results: list, voice: str,
                  speed: float, pause_ms: int, emit_progress):
    """保存 narration.json + tts_meta.json + 反写 segments.json"""

    # ── narration.json (分镜台时间线消费) ──
    narration = []
    for r in tts_results:
        narration.append({
            "index": r["index"],
            "seg_id": r["seg_id"],
            "start": r["start"],
            "end": r["end"],
            "narration": r["narration"],
            "pause_after_ms": r["pause_after_ms"],
            "overlaps_speech": r.get("overlaps_speech", False),
            "emotion": r.get("emotion", ""),
        })

    narr_path = task_dir / "narration.json"
    json.dump(narration, open(narr_path, "w"), ensure_ascii=False, indent=2)
    emit_progress("saved", f"📝 narration.json → {narr_path}")

    # ── tts_meta.json (配音台完整元数据) ──
    tts_meta = {
        "engine": "mimo-v2.5-tts",
        "voice": voice,
        "global_speed": speed,
        "global_pause_ms": pause_ms,
        "segments": tts_results,
        "narration": str(narr_path),
    }

    meta_path = task_dir / "tts_meta.json"
    json.dump(tts_meta, open(meta_path, "w"), ensure_ascii=False, indent=2)
    emit_progress("saved", f"📝 tts_meta.json → {meta_path}")

    # ── 反写 segments.json: audio_verified = true ──
    seg_file = task_dir / "segments.json"
    if seg_file.exists():
        seg_data = json.load(open(seg_file))
        seg_data["audio_verified"] = True
        # 可选: 为每个 segment 注入 audio_duration (分镜台消费)
        audio_map = {r["seg_id"]: r for r in tts_results}
        for seg in seg_data.get("segments", []):
            sid = seg.get("seg_id")
            if sid in audio_map:
                seg["audio_duration"] = audio_map[sid]["duration"]
                seg["audio_path"] = audio_map[sid]["audio_path"]
                seg["audio_emotion"] = audio_map[sid].get("emotion", "")
        json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)
        emit_progress("saved", "✅ segments.json: audio_verified=true + audio_duration 注入完成")
