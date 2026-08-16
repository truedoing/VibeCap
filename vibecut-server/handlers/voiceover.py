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
from config import resolve_work_dir, resolve_task_dir, GLOBAL_VOICES_DIR
from db import VibeCutDB

DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


# ═══════════════════════════════════════════════════════════════
# 全局音色库（预设 + 克隆音色）
# ═══════════════════════════════════════════════════════════════

from tts_engine import PRESET_VOICES

def _global_voice_registry_path() -> Path:
    return GLOBAL_VOICES_DIR / "voices.json"


def list_voices() -> list[dict]:
    """返回所有可用音色（预设 + 克隆），按名称排序。

    克隆音色条目：{"name", "label", "kind": "clone", "ref_audio", "ref_text"}
    预设音色条目：{"name", "label", "kind": "preset"}
    """
    presets = [{"name": name, "label": v.get("label", name), "kind": "preset"}
               for name, v in PRESET_VOICES.items()]
    clones = []
    registry = _global_voice_registry_path()
    if registry.exists():
        try:
            data = json.load(open(registry))
            for entry in data.get("voices", []):
                name = entry.get("name", "")
                if not name:
                    continue
                clones.append({
                    "name": name,
                    "label": entry.get("label", name),
                    "kind": "clone",
                    "ref_audio": entry.get("ref_audio", ""),
                    "ref_text": entry.get("ref_text", ""),
                })
        except Exception:
            pass
    return presets + clones


def create_clone_voice(name: str, ref_audio: str, ref_text: str = "") -> dict:
    """新建克隆音色（全局共享）。ref_audio 为参考音频的本地绝对路径。

    Returns:
        {"ok": True, "voice": {...}}
        {"ok": False, "error": str}
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "音色名不能为空"}
    if not ref_audio or not Path(ref_audio).exists():
        return {"ok": False, "error": f"参考音频不存在: {ref_audio}"}

    GLOBAL_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    registry = _global_voice_registry_path()
    data = {"voices": []}
    if registry.exists():
        try:
            data = json.load(open(registry))
        except Exception:
            data = {"voices": []}

    # 同名覆盖
    data["voices"] = [v for v in data.get("voices", []) if v.get("name") != name]
    entry = {
        "name": name,
        "label": name,
        "ref_audio": str(Path(ref_audio).resolve()),
        "ref_text": (ref_text or "").strip(),
    }
    data["voices"].append(entry)
    json.dump(data, open(registry, "w"), ensure_ascii=False, indent=2)
    return {"ok": True, "voice": {"name": name, "label": name, "kind": "clone",
                                  "ref_audio": entry["ref_audio"], "ref_text": entry["ref_text"]}}


def resolve_voice_ref(voice: str) -> tuple[str | None, str | None]:
    """根据音色名解析 (ref_audio_path, ref_text)。

    预设音色返回 (None, None)；克隆音色返回 (ref_audio, ref_text)。
    未知音色返回 (None, None)（按预设音色名直接传给 MiMo）。
    """
    registry = _global_voice_registry_path()
    if not registry.exists():
        return None, None
    try:
        data = json.load(open(registry))
        for entry in data.get("voices", []):
            if entry.get("name") == voice:
                return entry.get("ref_audio"), entry.get("ref_text", "")
    except Exception:
        pass
    return None, None


def resolve_tts_dir(task_name: str = None) -> Path:
    """TTs 音频输出目录"""
    return resolve_work_dir(task_name) / "tts_segments"


# ═══════════════════════════════════════════════════════════════
# 音色试听
# ═══════════════════════════════════════════════════════════════

VOICE_SAMPLE_TEXT = (
    "你好，欢迎使用VibeCut配音台。这是一段音色试听样本，"
    "帮助你选择合适的配音风格。"
)


def preview_voice(task_name: str, voice: str, force: bool = False) -> dict:
    """生成/返回音色试听样本 (磁盘缓存)

    Returns:
        {"ok": True, "audio_path": str, "duration": float}
        {"ok": False, "error": str}
    """
    from tts_engine import generate_speech, _get_audio_duration

    tts_dir = resolve_tts_dir(task_name)
    tts_dir.mkdir(parents=True, exist_ok=True)

    sample_path = tts_dir / f"_voice_sample_{voice}.wav"

    # 缓存命中
    if sample_path.exists() and not force:
        duration = _get_audio_duration(str(sample_path))
        return {
            "ok": True,
            "audio_path": f"tts_segments/_voice_sample_{voice}.wav",
            "duration": round(duration, 2),
            "cached": True,
        }

    # 生成新样本
    result = generate_speech(
        VOICE_SAMPLE_TEXT, str(sample_path),
        voice=voice,
        speed=1.0,
        style_hint="自然流畅的试听样本",
        timeout=60,
        retries=1,
    )

    if result["ok"]:
        return {
            "ok": True,
            "audio_path": f"tts_segments/_voice_sample_{voice}.wav",
            "duration": round(result["duration"], 2),
            "cached": False,
        }
    else:
        return {"ok": False, "error": result.get("error", "TTS 生成失败")}


def generate_voiceover(
    task_name: str,
    voice: str,
    speed: float,
    pause_ms: int,
    ref_audio_path: str | None,
    emit_progress,
    emit_complete,
    emit_error,
    seg_overrides: dict | None = None,
):
    """配音台 SSE 主流程

    流程:
      1. 加载 segments.json
      2. 配音师 Agent 设计配音方案 (LLM)
      3. 逐段 TTS 生成 (MiMo API)
      4. 保存 narration.json + tts_meta.json
    """
    from tts_engine import generate_speech, PRESET_VOICES

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

    # ── Phase 1: 配音方案（规则驱动，无 LLM 配音师） ──
    voice_plan = _default_voice_plan(narr_segments, speed, pause_ms)
    emit_progress("director_done",
        f"✅ 配音方案就绪: {len(voice_plan)}段 · 默认节奏",
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

        # 音频文件名用 seg_id（不是顺序 i），保证 timelineBuilder 用 sid 拼文件名时能找到
        out_path = tts_dir / f"narr_{seg_id:03d}.wav"

        seg_voice = voice  # 全局默认，可被段覆盖
        seg_emotion = plan.get("emotion", "narrative")
        seg_speed = plan.get("speed", speed)
        seg_pause = plan.get("pause_after_ms", pause_ms)
        emphasize = plan.get("emphasize", [])

        # ── 应用段级覆盖 ──
        ref_audio_for_seg = ref_audio_path
        override = (seg_overrides or {}).get(str(seg_id)) or (seg_overrides or {}).get(seg_id)
        if override:
            if override.get("voice") and override["voice"] in PRESET_VOICES:
                seg_voice = override["voice"]
            if override.get("emotion"):
                seg_emotion = override["emotion"]
            if override.get("speed") is not None:
                seg_speed = override["speed"]
            if override.get("pauseMs") is not None:
                seg_pause = override["pauseMs"]

        # ── 克隆音色解析：音色名对应全局音色库 → 参考音频 ──
        clone_ref_audio, clone_ref_text = resolve_voice_ref(seg_voice)
        if clone_ref_audio:
            ref_audio_for_seg = clone_ref_audio

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
            voice=seg_voice,
            speed=seg_speed,
            ref_audio_path=ref_audio_for_seg,
            ref_text=clone_ref_text,
            style_hint=style,
        )

        if result["ok"]:
            duration = round(result["duration"], 2)

            tts_results.append({
                "index": seg_id,
                "seg_id": seg_id,
                "start": round(current_time, 2),
                "end": round(current_time + duration, 2),
                "narration": text,
                "narration_text": text,
                "audio_path": f"tts_segments/narr_{seg_id:03d}.wav",
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
        "tts_meta_path": str(task_dir / "work_dir" / "tts_meta.json"),
        "narration_path": str(task_dir / "work_dir" / "narration.json"),
    })


# ═══════════════════════════════════════════════════════════════
# 配音方案（规则驱动，无 LLM 配音师）
# ═══════════════════════════════════════════════════════════════

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
    """保存 narration.json + tts_meta.json + 反写 segments.json

    narration.json / tts_meta.json 写入 work_dir/（与 api_narration、import_voiceover_audio 读取路径一致）；
    segments.json 反写在 task 根目录。
    """
    work_dir = task_dir / "work_dir"
    work_dir.mkdir(parents=True, exist_ok=True)

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

    narr_path = work_dir / "narration.json"
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

    meta_path = work_dir / "tts_meta.json"
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


# ═══════════════════════════════════════════════════════════════
# 单段更新
# ═══════════════════════════════════════════════════════════════

def _update_single_segment_result(task_dir: Path, seg_id, result: dict):
    """更新单个段的产物文件 (narration.json / tts_meta.json / segments.json)

    result 形状:
        {"index", "seg_id", "start", "end", "narration", "audio_path",
         "duration", "pause_after_ms", "emotion", "speed", "voice"}

    注意: 只更新该段的字段，后续段的 start/end 不做级联偏移。
    单段 duration 差异通常 <5s，允许用户重新批量生成获得精确时间线。
    """
    work_dir = task_dir / "work_dir"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. narration.json ──
    narr_path = work_dir / "narration.json"
    if narr_path.exists():
        narration = json.load(open(narr_path))
        for entry in narration:
            if entry.get("seg_id") == seg_id:
                entry["start"] = result["start"]
                entry["end"] = result["end"]
                if "emotion" in result:
                    entry["emotion"] = result["emotion"]
                if "pause_after_ms" in result:
                    entry["pause_after_ms"] = result["pause_after_ms"]
                break
        json.dump(narration, open(narr_path, "w"), ensure_ascii=False, indent=2)

    # ── 2. tts_meta.json ──
    meta_path = work_dir / "tts_meta.json"
    if meta_path.exists():
        meta = json.load(open(meta_path))
        for seg in meta.get("segments", []):
            if seg.get("seg_id") == seg_id:
                for k in ("start", "end", "duration", "audio_path",
                          "emotion", "speed", "pause_after_ms"):
                    if k in result:
                        seg[k] = result[k]
                if "voice" in result:
                    seg["voice"] = result["voice"]
                break
        json.dump(meta, open(meta_path, "w"), ensure_ascii=False, indent=2)

    # ── 3. segments.json ──
    seg_file = task_dir / "segments.json"
    if seg_file.exists():
        seg_data = json.load(open(seg_file))
        for seg in seg_data.get("segments", []):
            if seg.get("seg_id") == seg_id:
                seg["audio_duration"] = result["duration"]
                seg["audio_path"] = result["audio_path"]
                if "emotion" in result:
                    seg["audio_emotion"] = result["emotion"]
                break
        json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# 单段重生成
# ═══════════════════════════════════════════════════════════════

def regenerate_segment(
    task_name: str,
    seg_id,
    voice: str | None,
    emotion: str | None,
    speed: float | None,
    pause_ms: int | None,
    ref_audio_path: str | None,
    emit_progress,
    emit_complete,
    emit_error,
):
    """单段重生成 — 跳过 VoiceDirector，直接根据传入参数合成 TTS

    SSE 事件:
      segment_start → segment_done → complete
    或
      segment_error → error
    """
    from tts_engine import generate_speech, PRESET_VOICES

    # ── 1. 加载 segments.json ──
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

    # 找到目标段
    target = None
    target_index = 0
    for i, seg in enumerate(segments):
        if seg.get("seg_id") == seg_id:
            target = seg
            target_index = i
            break
    if target is None:
        emit_error("段不存在", f"seg_id={seg_id} 在 segments.json 中不存在")
        return

    narr_text = (target.get("narration_text") or "").strip()
    if not narr_text:
        emit_error("段无解说词", f"seg_id={seg_id} 无 narration_text")
        return

    # ── 2. 加载已有 tts_meta.json 获取原参数 ──
    meta_path = resolve_work_dir(task_name) / "tts_meta.json"
    original_emotion = "narrative"
    original_speed = 1.0
    original_pause = 300
    original_voice = voice or "白桦"

    if meta_path.exists():
        try:
            meta = json.load(open(meta_path))
            original_voice = meta.get("voice", original_voice)
            for seg in meta.get("segments", []):
                if seg.get("seg_id") == seg_id:
                    original_emotion = seg.get("emotion", original_emotion)
                    original_speed = seg.get("speed", original_speed)
                    original_pause = seg.get("pause_after_ms", original_pause)
                    break
        except Exception:
            pass

    # ── 3. 合并覆盖参数 ──
    final_voice = voice or original_voice
    final_emotion = emotion or original_emotion
    final_speed = speed if speed is not None else original_speed
    final_pause = pause_ms if pause_ms is not None else original_pause

    # ── 4. 计算 start/end ──
    prev_end = 0.0
    if meta_path.exists():
        try:
            meta = json.load(open(meta_path))
            for seg in meta.get("segments", []):
                if seg.get("seg_id") == seg_id:
                    break
                prev_end = seg.get("end", 0) + seg.get("pause_after_ms", 300) / 1000.0
        except Exception:
            pass

    # ── 5. 生成 style_hint ──
    emotion_hints = {
        "suspense": "压低声音，制造悬念感，语气神秘",
        "narrative": "平稳叙述，咬字清晰，自然流畅",
        "passionate": "声音饱满有力，情绪激昂，富有感染力",
        "analytical": "冷静克制，语气理性，有说服力",
        "warm": "温暖柔和，娓娓道来，有治愈感",
        "humorous": "语气轻快，带一点调侃感，自然不刻意",
    }
    style = emotion_hints.get(final_emotion, "自然叙述")

    # ── 6. TTS 生成 ──
    tts_dir = resolve_tts_dir(task_name)
    tts_dir.mkdir(parents=True, exist_ok=True)
    out_path = tts_dir / f"narr_{seg_id:03d}.wav"

    # 克隆音色解析：音色名 → 参考音频
    seg_ref_audio = ref_audio_path
    seg_ref_text = None
    clone_ref_audio, clone_ref_text = resolve_voice_ref(final_voice)
    if clone_ref_audio:
        seg_ref_audio = clone_ref_audio
        seg_ref_text = clone_ref_text

    emit_progress("segment_start",
        f"🔄 重生成 S{seg_id} | {final_emotion} | {narr_text[:30]}...",
        {"seg_id": seg_id, "index": target_index, "emotion": final_emotion,
         "voice": final_voice, "speed": final_speed})

    result = generate_speech(
        narr_text, str(out_path),
        voice=final_voice,
        speed=final_speed,
        ref_audio_path=seg_ref_audio,
        ref_text=seg_ref_text,
        style_hint=style,
    )

    if not result["ok"]:
        emit_progress("segment_error",
            f"❌ S{seg_id} 重生成失败: {result.get('error', '?')[:60]}",
            {"seg_id": seg_id, "error": result.get("error", "")})
        emit_error("单段重生成失败", result.get("error", ""))
        return

    duration = round(result["duration"], 2)
    new_end = round(prev_end + duration, 2)

    result_dict = {
        "index": target_index,
        "seg_id": seg_id,
        "start": round(prev_end, 2),
        "end": new_end,
        "narration": narr_text,
        "audio_path": f"tts_segments/narr_{seg_id:03d}.wav",
        "duration": duration,
        "pause_after_ms": final_pause,
        "emotion": final_emotion,
        "speed": final_speed,
        "voice": final_voice,
    }

    emit_progress("segment_done",
        f"✅ S{seg_id} 重生成完成 | {duration:.1f}s",
        {"seg_id": seg_id, "index": target_index,
         "duration": duration, "emotion": final_emotion,
         "speed": final_speed, "voice": final_voice})

    # ── 7. 更新产物文件 ──
    _update_single_segment_result(task_dir, seg_id, result_dict)

    emit_complete({
        "ok": True,
        "seg_id": seg_id,
        "duration": duration,
        "emotion": final_emotion,
        "voice": final_voice,
        "audio_path": result_dict["audio_path"],
    })


# ═══════════════════════════════════════════════════════════════
# 音频导入 (整段解说音频 → ASR对齐 → 切分)
# ═══════════════════════════════════════════════════════════════

def import_voiceover_audio(
    task_name: str,
    audio_path: str,
    emit_progress,
    emit_complete,
    emit_error,
):
    """导入整段解说音频，本地 ASR → 文案对齐 → 切分 narr_*.wav

    复用 cli/asr_narration.py (faster-whisper ASR) + cli/match_split.py (对齐切分)，
    在 handler 层补齐 segments.json 的 audio_verified/audio_duration 反写。

    SSE 事件: init → asr → split → saved → complete
    """
    from lib.subprocess_runner import run_script

    task_dir = resolve_task_dir(task_name)
    work_dir = task_dir / "work_dir"

    # ── 1. 校验音频 ──
    if not audio_path:
        emit_error("缺少音频路径", "请提供解说音频的本地路径 (audio_path)")
        return

    src = Path(audio_path)
    if not src.exists():
        # 回退: 任务目录下已有的 解说音频.wav
        fallback = task_dir / "解说音频.wav"
        if fallback.exists():
            src = fallback
        else:
            emit_error("音频不存在", f"路径: {audio_path}")
            return

    if src.suffix.lower() not in (".wav", ".mp3"):
        emit_error("不支持的格式", f"仅支持 wav/mp3，收到: {src.suffix}")
        return

    # ── 2. 拷贝到标准位置 ──
    dest = task_dir / f"解说音频{src.suffix.lower()}"
    if src.resolve() != dest.resolve():
        import shutil
        shutil.copy(src, dest)
        emit_progress("init", f"📥 音频已就位: {dest.name} ({dest.stat().st_size/1024/1024:.1f}MB)")
    else:
        emit_progress("init", f"📥 音频已就位: {dest.name}")

    # 校验 segments.json 存在 (match_split 需要)
    seg_file = task_dir / "segments.json"
    if not seg_file.exists():
        seg_file = PROJECT_DIR / "tasks" / "segments.json"
    if not seg_file.exists():
        seg_file = PROJECT_DIR / "tasks" / "文案脚本.json"
    if not seg_file.exists():
        emit_error("无脚本", "请先在编剧台生成 segments.json (match_split 需要文案)")
        return

    # ── 3. ASR 转写 ──
    emit_progress("asr", "🎧 ASR 转写解说音频 (faster-whisper)...")
    env_extra = {"VibeCut_DRAMA": project_name, "VibeCut_TASK": task_name,
                 "KMP_DUPLICATE_LIB_OK": "TRUE"}
    r_asr = run_script("asr_narration.py", timeout=600, env_extra=env_extra)
    if not r_asr["ok"]:
        emit_error("ASR 转写失败", r_asr.get("error", ""))
        return
    emit_progress("asr_done", "✅ ASR 转写完成 → narration_asr.json")

    # ── 4. 对齐 + 切分 ──
    emit_progress("split", "✂️ 文案↔ASR 对齐 → 切分 narr_*.wav...")
    r_split = run_script("match_split.py", timeout=120, env_extra=env_extra)
    if not r_split["ok"]:
        emit_error("切分失败", r_split.get("error", ""))
        return
    emit_progress("split_done", "✅ 切分完成 → tts_segments/narr_*.wav")

    # ── 5. 补 gap: 反写 segments.json ──
    meta_path = work_dir / "tts_meta.json"
    if not meta_path.exists():
        emit_error("tts_meta.json 未生成", "match_split 未产出 tts_meta.json")
        return

    try:
        meta = json.load(open(meta_path))
        seg_data = json.load(open(seg_file))
        seg_data["audio_verified"] = True

        # match_split 的 tts_meta segments 用 "index" 字段存 seg_id 值
        audio_map = {}
        for m in meta.get("segments", []):
            sid = m.get("seg_id", m.get("index"))
            if sid is not None and m.get("narration"):
                audio_map[sid] = m

        for seg in seg_data.get("segments", []):
            sid = seg.get("seg_id")
            if sid in audio_map:
                m = audio_map[sid]
                seg["audio_duration"] = round(m.get("end", 0) - m.get("start", 0), 2)
                # 用相对文件名 (前端 /tts_segments/ 会映射到 work_dir/tts_segments/)
                ap = m.get("audio_path", "")
                seg["audio_path"] = f"tts_segments/{Path(ap).name}" if ap else f"tts_segments/narr_{sid:03d}.wav"
                seg["audio_emotion"] = m.get("emotion", "自然叙述")

        json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)
        emit_progress("saved", "✅ segments.json: audio_verified=true + audio_duration 注入完成")
    except Exception as e:
        emit_error("产物回写失败", str(e)[:200])
        return

    emit_complete({
        "ok": True,
        "total_segments": len(audio_map),
        "tts_meta_path": str(meta_path),
        "audio_path": str(dest),
    })
