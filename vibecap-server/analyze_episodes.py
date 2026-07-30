#!/usr/bin/env python3
"""
EP1-3 分析脚本：场景切分 → ASR 转写 → VLM 画面分析
直接调 MiMo API（不依赖 video-recap-skills）

用法:
  python3 analyze_episodes.py --ep 1 --video "/Users/zgl/解说剪辑/都挺好原剧/都挺好 01_1080p.mp4"
  python3 analyze_episodes.py --ep 1,2,3  # 批量
"""

import json, re, subprocess, base64, os, time, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

BASE_DIR = Path("/Users/zgl/VIBECAP")
DRAMA_DIR = BASE_DIR / "都挺好"
SRC_VIDEOS = Path("/Users/zgl/解说剪辑/都挺好原剧")

# ── MiMo API 配置 ──
API_KEY = os.environ.get("MIMO_API_KEY", "")
API_URL = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
ASR_MODEL = "mimo-v2.5-asr"
VLM_MODEL = "mimo-v2.5"

def api_call(payload, timeout=120):
    """通用 MiMo API 调用"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def run_ffmpeg(cmd, timeout=180):
    """运行 ffmpeg 命令"""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {result.stderr[-300:]}")
    return result

# ═══════════════════════════════════════════════════════════════
# Step 1: 场景切分
# ═══════════════════════════════════════════════════════════════

def detect_scenes(video_path, work_dir, segment_duration):
    """按固定时长切分场景 → scenes.json（简单可靠，避免 ffmpeg scdet 切太碎）"""
    scenes_file = work_dir / "scenes.json"
    if scenes_file.exists():
        print(f"  scenes.json 已存在，跳过")
        return json.load(open(scenes_file))

    # 获取视频总时长
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    total_dur = float(result.stdout.strip())

    print(f"  按 {segment_duration}s 间隔切分场景...")
    scenes = []
    cursor = 0.0
    while cursor < total_dur:
        end = min(cursor + segment_duration, total_dur)
        scenes.append({"start": round(cursor, 2), "end": round(end, 2)})
        cursor = end

    print(f"  → {len(scenes)} 个场景")
    json.dump(scenes, open(scenes_file, 'w'), ensure_ascii=False, indent=2)
    return scenes


# ═══════════════════════════════════════════════════════════════
# Step 2: ASR 转写
# ═══════════════════════════════════════════════════════════════

def extract_audio(video_path, work_dir):
    """提取音频为 16kHz 单声道 wav"""
    audio_path = work_dir / "audio.wav"
    if audio_path.exists():
        print(f"  audio.wav 已存在，跳过")
        return audio_path

    print("  提取音频...")
    run_ffmpeg([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1",
        str(audio_path)
    ])
    return audio_path


def transcribe_asr(audio_path, work_dir, model_size="small"):
    """本地 faster-whisper 转写 → asr_result.json（含置信度）"""
    asr_file = work_dir / "asr_result.json"
    if asr_file.exists():
        print(f"  asr_result.json 已存在，跳过（删除后重跑可重新转写）")
        return json.load(open(asr_file))

    print(f"  本地 ASR 转写中 (faster-whisper {model_size})...")
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_out, info = model.transcribe(str(audio_path), language="zh", beam_size=5,
                                           vad_filter=True,
                                           vad_parameters=dict(min_silence_duration_ms=500))

    segments = []
    for seg in segments_out:
        segments.append({
            "start": round(seg.start, 1),
            "end": round(seg.end, 1),
            "text": seg.text.strip(),
            "confidence": round(seg.avg_logprob, 3),  # 置信度
            "words": [
                {"word": w.word, "start": round(w.start, 2), "end": round(w.end, 2),
                 "confidence": round(w.probability, 3)}
                for w in (seg.words or [])
            ] if seg.words else []
        })

    json.dump(segments, open(asr_file, 'w'), ensure_ascii=False, indent=2)
    total_text = " ".join(s["text"] for s in segments)
    low_conf = sum(1 for s in segments if s["confidence"] < -1.5)
    print(f"  → {len(segments)} 段, {len(total_text)} 字, 低置信度: {low_conf}")
    for s in segments[:5]:
        print(f"    [{s['start']:.1f}s] conf={s['confidence']:.1f} {s['text'][:80]}")
    return segments


# ═══════════════════════════════════════════════════════════════
# Step 3: 提帧
# ═══════════════════════════════════════════════════════════════

def extract_frames(video_path, work_dir, fps=1):
    """提取关键帧 → frames/ 目录"""
    frames_dir = work_dir / "frames"
    if frames_dir.exists() and len(list(frames_dir.glob("*.jpg"))) > 10:
        print(f"  frames/ 已存在，跳过")
        return sorted(frames_dir.glob("*.jpg"))

    frames_dir.mkdir(exist_ok=True)
    print(f"  提取关键帧 (fps={fps})...")

    run_ffmpeg([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps={fps}",
        str(frames_dir / "frame_%05d.jpg")
    ])

    frames = sorted(frames_dir.glob("*.jpg"))
    print(f"  → {len(frames)} 帧")
    return frames


# ═══════════════════════════════════════════════════════════════
# Step 4: VLM 画面分析
# ═══════════════════════════════════════════════════════════════

def load_background_context(work_dir):
    """加载角色上下文"""
    bg_file = work_dir / "background_research.json"
    if not bg_file.exists():
        return ""

    try:
        data = json.load(open(bg_file))
        chars = data.get("characters", {})
        ctx = "已知角色信息：\n"
        for name, desc in chars.items():
            ctx += f"- {name}: {desc}\n"

        if "visual_notes" in data:
            ctx += f"\n场景参考：{json.dumps(data['visual_notes'], ensure_ascii=False)[:800]}\n"

        return ctx
    except Exception:
        return ""


def analyze_scene_vlm(scene_index, scene, frames, frame_times, background_ctx, work_dir):
    """对单个场景调用 VLM 分析"""
    start, end = scene["start"], scene["end"]

    # 选择该场景内的帧（最多 8 帧）
    scene_frames = [f for f in frames if start <= frame_times.get(f, 0) <= end]
    if not scene_frames:
        mid = (start + end) / 2
        scene_frames = [min(frames, key=lambda f: abs(frame_times.get(f, 999) - mid))]

    max_f = min(8, max(3, round((end - start) / 5)))
    if len(scene_frames) > max_f:
        step = len(scene_frames) / max_f
        scene_frames = [scene_frames[int(j * step)] for j in range(max_f)]

    # 构建 VLM 请求
    content_parts = []
    for f in scene_frames:
        b64 = base64.b64encode(f.read_bytes()).decode()
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    prompt = (
        "仔细观察这些视频关键帧，用中文描述画面内容。按以下格式输出：\n\n"
        "【描述】\n不超过150字，描述画面中的人物（用真名）、动作、场景、构图、光线。必须使用具体人名，禁止用「他」「她」。\n\n"
        "【字幕】\n如果画面中出现了硬字幕（画面底部或顶部的对白文字），请逐条列出原文。\n"
        "注意：演职人员表、出品人名单等片头片尾信息不算字幕，不要列出。\n"
        "格式：每条一行，不要编号。如果没有字幕，写「无」。\n\n"
        "【深层分析】\n1. 角色情绪：\n2. 人物关系：\n3. 场景变化：\n4. 关键视角：\n5. 台词潜台词：\n\n"
        "【帧标签】\n每帧一行，格式: 「秒数s | 标签1, 标签2, 标签3」\n"
        "标签内容：人物名、动作、表情、构图、场景。\n"
    )
    if background_ctx:
        prompt = background_ctx + "\n\n" + prompt

    content_parts.append({"type": "text", "text": prompt})

    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 2000,
    }

    for attempt in range(3):
        try:
            resp = api_call(payload)
            raw = resp["choices"][0]["message"].get("content", "")
            if raw.strip():
                break
        except Exception as e:
            if attempt == 2:
                return scene_index, {"error": str(e)}
            time.sleep(2)

    # 解析响应
    desc_match = re.search(r'【描述】\s*\n?(.*?)(?=【字幕】|【帧标签】|【深层分析】|$)', raw, re.DOTALL)
    description = desc_match.group(1).strip() if desc_match else raw[:200]

    # 字幕提取 — VLM 结构化输出
    subtitles = []
    sub_match = re.search(r'【字幕】\s*\n?(.*?)(?=【描述】|【帧标签】|【深层分析】|$)', raw, re.DOTALL)
    if sub_match:
        sub_text = sub_match.group(1).strip()
        if sub_text and sub_text != '无':
            subtitles = [l.strip() for l in sub_text.split('\n') if l.strip() and len(l.strip()) > 1]

    depth_match = re.search(r'【深层分析】\s*\n?(.*?)(?=【描述】|【字幕】|【帧标签】|$)', raw, re.DOTALL)
    depth_analysis = depth_match.group(1).strip() if depth_match else ""

    frame_facts = {}
    facts_match = re.search(r'【帧标签】\s*\n?(.*?)(?=【描述】|【字幕】|【深层分析】|$)', raw, re.DOTALL)
    if facts_match:
        for line in facts_match.group(1).strip().split("\n"):
            m = re.match(r'([\d.]+)\s*s?\s*\|\s*(.+)', line.strip())
            if m:
                ts = m.group(1)
                frame_facts[ts] = [a.strip() for a in re.split(r"[，,；;、]+", m.group(2)) if a.strip()]

    result = {
        "scene_id": scene_index,
        "start": round(start, 2),
        "end": round(end, 2),
        "description": description,
        "depth_analysis": depth_analysis,
    }
    if subtitles:
        result["subtitles"] = subtitles
    if frame_facts:
        result["frame_facts"] = frame_facts

    return scene_index, result


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def analyze_episode(ep, video_path, segment_duration=10, asr_model="small"):
    """完整分析一集"""
    work_dir = DRAMA_DIR / "sources" / f"ep{ep}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 确保 background_research.json 存在
    bg_src = DRAMA_DIR / "character_portraits" / "background_research.json"
    bg_dst = work_dir / "background_research.json"
    if bg_src.exists() and not bg_dst.exists():
        import shutil
        shutil.copy(bg_src, bg_dst)

    print(f"\n{'='*60}")
    print(f"EP{ep} 分析: {video_path.name}")
    print(f"输出目录: {work_dir}")
    print(f"{'='*60}")

    # Step 1: 场景切分
    print("\n[1/4] 场景切分")
    scenes = detect_scenes(video_path, work_dir, segment_duration)

    # Step 2: ASR
    print("\n[2/4] ASR 转写")
    audio_path = extract_audio(video_path, work_dir)
    asr_segments = transcribe_asr(audio_path, work_dir, model_size=asr_model)

    # Step 3: 提帧
    print("\n[3/4] 提取关键帧")
    frames = extract_frames(video_path, work_dir)

    # 构建帧时间映射
    fps = 1
    frame_times = {}
    for f in frames:
        parts = f.stem.split("_")
        if len(parts) == 2 and parts[1].isdigit():
            t = int(parts[1]) / fps
            frame_times[f] = t

    # Step 4: VLM
    print(f"\n[4/4] VLM 画面分析 ({len(scenes)} 个场景)")

    # 检查断点续传
    cache_file = work_dir / "vlm_scene_cache.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.load(open(cache_file))
            print(f"  加载缓存: {len(cache)} 个已完成场景")
        except Exception:
            pass

    background_ctx = load_background_context(work_dir)
    results = [None] * len(scenes)
    todo = [i for i in range(len(scenes)) if str(i) not in cache]

    if todo:
        print(f"  待分析: {len(todo)}/{len(scenes)}")

        # 并行分析（API 限流 100 RPM，12 并发约 40 RPM，安全）
        with ThreadPoolExecutor(max_workers=args.vlm_workers) as executor:
            futures = {
                executor.submit(
                    analyze_scene_vlm, i, scenes[i], frames, frame_times, background_ctx, work_dir
                ): i for i in todo
            }
            for future in as_completed(futures):
                i = futures[future]
                try:
                    idx, result = future.result()
                    results[idx] = result
                    cache[str(idx)] = result
                    # 每完成一个就保存
                    json.dump(cache, open(cache_file, 'w'), ensure_ascii=False, indent=2)
                    desc_preview = result.get("description", "")[:60]
                    print(f"  [{idx+1}/{len(scenes)}] {desc_preview}...")
                except Exception as e:
                    print(f"  场景 {i+1} 失败: {e}")
    else:
        results = [cache[str(i)] for i in range(len(scenes))]
        print(f"  全部复用缓存")

    # 保存最终结果
    vlm_file = work_dir / "vlm_analysis.json"
    json.dump(results, open(vlm_file, 'w'), ensure_ascii=False, indent=2)
    cache_file.unlink(missing_ok=True)

    print(f"\n✅ EP{ep} 完成: {len(scenes)} 场景, {len(asr_segments)} ASR段")
    return results


def main():
    parser = argparse.ArgumentParser(description="EP1-3 分析脚本")
    parser.add_argument("--ep", default="1,2,3", help="要分析的集数 (逗号分隔)")
    parser.add_argument("--segment", type=int, default=10, help="场景切分间隔(秒)，默认10")
    parser.add_argument("--skip-asr", action="store_true", help="跳过 ASR")
    parser.add_argument("--skip-vlm", action="store_true", help="跳过 VLM")
    parser.add_argument("--asr-model", default="small", choices=["tiny", "small", "medium"],
                        help="faster-whisper 模型大小 (默认 small)")
    parser.add_argument("--vlm-workers", type=int, default=12,
                        help="VLM 并发数 (默认 12, API 限流 100 RPM)")
    args = parser.parse_args()

    episodes = [int(e.strip()) for e in args.ep.split(",")]

    for ep in episodes:
        video_path = SRC_VIDEOS / f"都挺好 {ep:02d}_1080p.mp4"
        if not video_path.exists():
            print(f"❌ 找不到视频: {video_path}")
            continue
        analyze_episode(ep, video_path, args.segment, args.asr_model)


if __name__ == "__main__":
    main()
