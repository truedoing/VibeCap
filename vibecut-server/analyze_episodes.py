#!/usr/bin/env python3
"""
EP VLM 分析脚本 v3 — 三层推理 + 结构化视觉元数据

Layer 1: DeepSeek 读 ASR + 剧情概要 → 结构化场景-人物映射 (scene_map.json)
Layer 2: ASR 关键词锚定场景时间边界
Layer 3: VLM 结构化画面理解 → 场景段级视觉元数据 (vlm_seg_cache_v3.json)

用法:
  python3 analyze_episodes.py --ep 41                      # 完整一集
  python3 analyze_episodes.py --ep 41 --no-proxy            # 强制 1080p
"""

import json, re, subprocess, base64, os, time, argparse
from pathlib import Path
import urllib.request

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
DRAMA_DIR = BASE_DIR / "都挺好"
SRC_VIDEOS = Path("/Users/zgl/解说剪辑/都挺好原剧")
PROXY_DIR = DRAMA_DIR / "proxies"

API_KEY = os.environ.get("MIMO_API_KEY", "")
API_URL = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
VLM_MODEL = "mimo-v2.5"

KNOWN_CHARACTERS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '朱丽', '吴非', '赵美兰', '小蔡', '老聂']

def api_call(payload, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def run_ffmpeg(cmd, timeout=180):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {result.stderr[-300:]}")
    return result


# ═══════════════════════════════════ Step 1: 场景切分 ═══════════════════════════════════

def detect_scenes(video_path, work_dir, segment_duration=10, max_duration=None):
    scenes_file = work_dir / "scenes.json"
    if scenes_file.exists() and not max_duration:
        print(f"  scenes.json 已存在, 跳过")
        return json.load(open(scenes_file))

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    total_dur = float(result.stdout.strip())
    if max_duration:
        total_dur = min(total_dur, max_duration)

    print(f"  按 {segment_duration}s 切分 (总长 {total_dur:.0f}s)...")
    scenes = []
    cursor = 0.0
    while cursor < total_dur:
        end = min(cursor + segment_duration, total_dur)
        scenes.append({"start": round(cursor, 2), "end": round(end, 2)})
        cursor = end

    print(f"  → {len(scenes)} 个场景")
    json.dump(scenes, open(scenes_file, 'w'), ensure_ascii=False, indent=2)
    return scenes


# ═══════════════════════════════════ Step 2: ASR ═══════════════════════════════════

def extract_audio(video_path, work_dir):
    audio_path = work_dir / "audio.wav"
    if audio_path.exists():
        return audio_path
    print("  提取音频...")
    run_ffmpeg(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1", str(audio_path)])
    return audio_path

def transcribe_asr(audio_path, work_dir, model_size="small"):
    asr_file = work_dir / "asr_result.json"
    if asr_file.exists():
        return json.load(open(asr_file))
    print(f"  ASR (faster-whisper {model_size})...")
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_out, _ = model.transcribe(str(audio_path), language="zh", beam_size=5,
                                        vad_filter=True,
                                        vad_parameters=dict(min_silence_duration_ms=500))
    segments = []
    for seg in segments_out:
        segments.append({
            "start": round(seg.start, 1), "end": round(seg.end, 1),
            "text": seg.text.strip(), "confidence": round(seg.avg_logprob, 3),
            "words": [{"word": w.word, "start": round(w.start, 2), "end": round(w.end, 2),
                       "confidence": round(w.probability, 3)} for w in (seg.words or [])] if seg.words else []
        })
    json.dump(segments, open(asr_file, 'w'), ensure_ascii=False, indent=2)
    print(f"  → {len(segments)} 段")
    return segments


# ═══════════════════════════════════ Step 3: 提帧 ═══════════════════════════════════

def extract_frames(video_path, work_dir, fps=1):
    frames_dir = work_dir / "frames"
    if frames_dir.exists() and len(list(frames_dir.glob("*.jpg"))) > 10:
        return sorted(frames_dir.glob("*.jpg"))
    frames_dir.mkdir(exist_ok=True)
    print(f"  提取帧 (fps={fps})...")
    run_ffmpeg(["ffmpeg", "-y", "-i", str(video_path), "-vf", f"fps={fps}",
                 str(frames_dir / "frame_%05d.jpg")])
    frames = sorted(frames_dir.glob("*.jpg"))
    print(f"  → {len(frames)} 帧")
    return frames


# ═══════════════════════════════════ Step 4: Scene Map ═══════════════════════════════════

SCENE_MAP_PROMPT = """你是《都挺好》的场记。根据 ASR 对话和剧情概要，推断本集的场景分段。

输出 JSON 数组，每个元素:
{
  "time_range": [start_s, end_s],
  "location": "地点",
  "characters": ["在场人物"],
  "event": "事件（≤20字）",
  "mood": "情绪"
}

规则:
1. 人物全名: 苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡/老聂
2. 按对话话题转换点切分, 每段 60-90s
3. 覆盖第一句到末句的完整时间线
4. 通过称呼词推断说话人（"明哲"→吴非在说话,"爸"→子女在说话）"""


def build_scene_map(asr_segments, synopsis, work_dir):
    cache_file = work_dir / "scene_map.json"
    if cache_file.exists():
        print(f"  scene_map.json 已存在, 跳过")
        return json.load(open(cache_file))

    asr_lines = []
    current_win = None
    for seg in asr_segments:
        win = int(seg['start'] // 30) * 30
        if win != current_win:
            asr_lines.append(f"\n[{win}s]")
            current_win = win
        asr_lines.append(seg['text'])
    asr_text = ' '.join(asr_lines)[:8000]

    user_prompt = f"剧情概要:\n{synopsis}\n\nASR (带时间戳):\n{asr_text}\n\n输出场景分段 JSON。"

    print("  DeepSeek 生成 scene_map...")
    result = _call_deepseek(SCENE_MAP_PROMPT, user_prompt, max_tokens=2000, label="scene_map")

    if not result.get("ok"):
        print(f"  DeepSeek 失败: {result.get('error')}, 使用 fallback")
        return _fallback_scene_map(asr_segments)

    content = result["content"]
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        try:
            scene_map = json.loads(json_match.group(0))
            # 过滤掉过长的段(>200s)和过短的段(<15s)
            scene_map = [sm for sm in scene_map if 15 < sm['time_range'][1] - sm['time_range'][0] < 300]
            json.dump(scene_map, open(cache_file, 'w'), ensure_ascii=False, indent=2)
            print(f"  → {len(scene_map)} 段")
            for sm in scene_map:
                print(f"    [{sm['time_range'][0]}s-{sm['time_range'][1]}s] {sm['location']}: {', '.join(sm['characters'])}")
            return scene_map
        except json.JSONDecodeError as e:
            print(f"  JSON 解析失败: {e}")
    return _fallback_scene_map(asr_segments)


def _fallback_scene_map(asr_segments):
    """关键词规则 fallback"""
    windows = {}
    for seg in asr_segments:
        win = int(seg['start'] // 30) * 30
        windows.setdefault(win, []).append(seg['text'])

    scenes = []
    current = None
    for win in sorted(windows.keys()):
        text = ' '.join(windows[win])
        if any(kw in text for kw in ['明哲', '吴非', '回美国', '房产证', '你怎么还不睡']):
            loc, chars = "苏明哲家(美国)", ["苏明哲", "吴非"]
        elif any(kw in text for kw in ['菜刀', '谁敢', '不让结婚', '我看谁敢', '你让开']):
            loc, chars = "苏大强家", ["苏大强", "苏明成", "小蔡"]
        elif any(kw in text for kw in ['贷款', '还十年', '一家人不说两家话', '聊聊', '谈判']):
            loc, chars = "苏大强家", ["苏明玉", "小蔡", "苏大强"]
        elif any(kw in text for kw in ['打官司', '卖房', '不孝', '赌气']):
            loc, chars = "苏大强家", ["苏大强", "苏明玉"]
        elif any(kw in text for kw in ['老聂', '劝', '喝酒']):
            loc, chars = "苏大强家", ["苏大强", "老聂"]
        elif any(kw in text for kw in ['明月', '大嫂', '明成', '办公室']):
            loc, chars = "苏明玉办公室", ["苏明玉"]
        elif any(kw in text for kw in ['明成', '朱丽', '小蔡家']):
            loc, chars = "苏明成家", ["苏明成", "朱丽"]
        else:
            loc, chars = "未知", []

        if current and current['location'] == loc and set(current['characters']) == set(chars):
            current['time_range'][1] = win + 30
        else:
            if current: scenes.append(current)
            current = {"time_range": [win, win + 30], "location": loc, "characters": chars, "event": "", "mood": ""}
    if current: scenes.append(current)

    # 合并相邻同类段
    merged = []
    for s in scenes:
        if merged and merged[-1]['location'] == s['location'] and \
           set(merged[-1]['characters']) == set(s['characters']) and \
           s['time_range'][0] - merged[-1]['time_range'][1] < 60:
            merged[-1]['time_range'][1] = s['time_range'][1]
        else:
            merged.append(s)
    print(f"  → fallback: {len(merged)} 段")
    return merged


def _call_deepseek(system, user, max_tokens=2000, label="deepseek"):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "no DEEPSEEK_API_KEY"}
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3, "max_tokens": max_tokens,
    }).encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            content = resp["choices"][0]["message"].get("content", "")
            usage = resp.get("usage", {})
            print(f"    [{label}] in:{usage.get('prompt_tokens',0)} out:{usage.get('completion_tokens',0)}")
            return {"ok": True, "content": content, "usage": usage}
        except Exception as e:
            if attempt == 2: return {"ok": False, "error": str(e)}
            time.sleep(2)


def _generate_synopsis(asr_segments, ep):
    """DeepSeek 读取 ASR 生成剧情概要"""
    asr_text = ' '.join(seg['text'] for seg in asr_segments)[:6000]
    result = _call_deepseek(
        "你是电视剧《都挺好》的编剧助理。根据对话记录，概括这集的核心剧情，"
        "按时间顺序列出 3-5 个关键情节段落。人物用全名（苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡等）。",
        f"第{ep}集对话记录:\n{asr_text}",
        max_tokens=800,
        label="synopsis",
    )
    if result.get("ok"):
        return result["content"].strip()
    return ""


# ═══════════════════════════════════ Step 5: VLM 画面分析 ═══════════════════════════════════

def pick_keyframes_for_segment(sm, frames, frame_times, max_frames=2):
    """每段取1-2帧，减少 VLM 内部思考消耗"""
    start, end = sm['time_range']
    seg_frames = sorted(
        [f for f in frames if start <= frame_times.get(f, -1) <= end],
        key=lambda f: frame_times.get(f, 0))
    if not seg_frames:
        mid_t = (start + end) / 2
        seg_frames = [min(frames, key=lambda f: abs(frame_times.get(f, 999) - mid_t))]
    if len(seg_frames) <= max_frames:
        return seg_frames
    step = (len(seg_frames) - 1) / (max_frames - 1)
    return [seg_frames[int(i * step)] for i in range(max_frames)]


def analyze_segment_vlm(seg_index, sm, frames, frame_times, prev_desc=""):
    """VLM 分析一个场景段 — 2帧 + 结构化JSON输出（v3: 导演级视觉元数据）"""
    start, end = sm['time_range']
    seg_frames = pick_keyframes_for_segment(sm, frames, frame_times)

    content_parts = []
    for f in seg_frames:
        b64 = base64.b64encode(f.read_bytes()).decode()
        content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    chars_str = '、'.join(sm.get('characters', [])) or '未知'
    loc_str = sm.get('location', '未知')
    event_str = sm.get('event', '未知')

    # v3: 结构化JSON输出 — 导演级视觉元数据
    prompt = (
        f"角色={chars_str}  地点={loc_str}  事件={event_str}\n"
        f"只用上述角色名，看不清就写衣色。\n"
        f"分析画面，输出 JSON（不要 markdown 代码块）:\n"
        f'{{\n'
        f'  "visual_summary": "≤80字画面描述",\n'
        f'  "shot_size": "特写/近景/中景/全景/远景/大远景",\n'
        f'  "composition": "单人/双人/三人/群像",\n'
        f'  "angle": "平视/俯拍/仰拍",\n'
        f'  "emotional_tone": "情绪标签≤8字",\n'
        f'  "intensity": 强度1-5,\n'
        f'  "lighting": "自然光/暖调/冷调/暗调/高调",\n'
        f'  "actions": ["动作1","动作2"]\n'
        f'}}'
    )
    if prev_desc:
        prompt = f"前情: {prev_desc}\n" + prompt

    content_parts.append({"type": "text", "text": prompt})

    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 1200,  # v3: 结构化JSON + 2帧描述 → 需要充足空间
    }

    raw = ""
    usage = {}
    for attempt in range(3):
        try:
            resp = api_call(payload)
            raw = resp["choices"][0]["message"].get("content", "")
            usage = resp.get("usage", {})
            if raw and raw.strip():
                break
            time.sleep(3)
        except Exception as e:
            if attempt == 2:
                return {"error": str(e), "start": start, "end": end}
            time.sleep(2)

    # ── JSON 解析 + 容错 ──
    parsed = _parse_vlm_json(raw)

    # 用 scene_map 信息补充：验证人物标签（从文本中提取已知角色名）
    visible_chars = [c for c in KNOWN_CHARACTERS if c in parsed.get("visual_summary", "")]
    # 也检查整个 raw 文本
    if not visible_chars:
        visible_chars = [c for c in KNOWN_CHARACTERS if c in raw]

    return {
        "scene_map_index": seg_index,
        "start": round(start, 2),
        "end": round(end, 2),
        "visual_summary": parsed.get("visual_summary", "")[:200],
        "shot_size": parsed.get("shot_size", "未知"),
        "composition": parsed.get("composition", "未知"),
        "angle": parsed.get("angle", "未知"),
        "emotional_tone": parsed.get("emotional_tone", ""),
        "intensity": parsed.get("intensity", 3),
        "lighting": parsed.get("lighting", "未知"),
        "actions": parsed.get("actions", []),
        "_tokens": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "_chars": visible_chars,
    }


def _parse_vlm_json(raw_text: str) -> dict:
    """解析 VLM 结构化 JSON 输出，多层容错"""
    VALID_SHOT_SIZES = {"特写", "近景", "中景", "全景", "远景", "大远景"}
    VALID_COMPOSITIONS = {"单人", "双人", "三人", "群像"}
    VALID_ANGLES = {"平视", "俯拍", "仰拍"}
    VALID_LIGHTING = {"自然光", "暖调", "冷调", "暗调", "高调"}
    DEFAULTS = {
        "visual_summary": "",
        "shot_size": "中景",
        "composition": "单人",
        "angle": "平视",
        "emotional_tone": "",
        "intensity": 3,
        "lighting": "自然光",
        "actions": [],
    }

    raw = raw_text.strip()

    # 0: 剥离 <thinking> 块 (MiMo 可能把推理内容塞进 thinking 标签)
    thinking_match = re.search(r'<thinking>(.*?)</thinking>', raw, re.DOTALL)
    if thinking_match:
        after_thinking = raw[thinking_match.end():].strip()
        if after_thinking:
            raw = after_thinking
        else:
            # thinking 块占满整个输出，尝试从其中提取描述性内容
            think_content = thinking_match.group(1)
            sentences = re.split(r'[。！？\n]', think_content)
            raw = sentences[-1].strip() if sentences else raw

    # 策略1: 直接解析全体 JSON
    result = _try_parse_json(raw)
    if result:
        return _validate_and_fill(result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                  VALID_ANGLES, VALID_LIGHTING, DEFAULTS)

    # 策略2: 提取 markdown 代码块中的 JSON
    code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if code_match:
        result = _try_parse_json(code_match.group(1))
        if result:
            return _validate_and_fill(result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                      VALID_ANGLES, VALID_LIGHTING, DEFAULTS)

    # 策略3: 提取第一个 { } 块
    brace_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if brace_match:
        result = _try_parse_json(brace_match.group(0))
        if result:
            return _validate_and_fill(result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                      VALID_ANGLES, VALID_LIGHTING, DEFAULTS)

    # 策略3.5: JSON 截断容错 — 尝试补全缺失的 } 再解析
    truncated = raw.strip()
    if truncated.startswith('{') and not truncated.rstrip().endswith('}'):
        # 计算缺失的闭合括号数
        open_cnt = truncated.count('{') - truncated.count('}')
        completed = truncated + '}' * open_cnt
        result = _try_parse_json(completed)
        if result:
            return _validate_and_fill(result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                      VALID_ANGLES, VALID_LIGHTING, DEFAULTS)
        # 尝试截断到最后一个逗号后补全
        last_comma = truncated.rfind(',')
        if last_comma > 0:
            completed = truncated[:last_comma] + '}' * (open_cnt + 1)
            result = _try_parse_json(completed)
            if result:
                return _validate_and_fill(result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                          VALID_ANGLES, VALID_LIGHTING, DEFAULTS)

    # 策略4: 正则提取 — 从截断/损坏的 JSON 中提取已知字段
    regex_result = {}
    for field, pattern in [
        ('visual_summary', r'"visual_summary"\s*:\s*"([^"]*)"'),
        ('shot_size', r'"shot_size"\s*:\s*"([^"]*)"'),
        ('composition', r'"composition"\s*:\s*"([^"]*)"'),
        ('angle', r'"angle"\s*:\s*"([^"]*)"'),
        ('emotional_tone', r'"emotional_tone"\s*:\s*"([^"]*)"'),
        ('lighting', r'"lighting"\s*:\s*"([^"]*)"'),
    ]:
        m = re.search(pattern, raw)
        if m:
            regex_result[field] = m.group(1)
    # intensity
    im = re.search(r'"intensity"\s*:\s*(\d+)', raw)
    if im:
        regex_result['intensity'] = int(im.group(1))
    # actions
    am = re.search(r'"actions"\s*:\s*(\[.*?\])', raw, re.DOTALL)
    if am:
        try:
            regex_result['actions'] = json.loads(am.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    if regex_result.get('visual_summary'):
        return _validate_and_fill(regex_result, VALID_SHOT_SIZES, VALID_COMPOSITIONS,
                                  VALID_ANGLES, VALID_LIGHTING, DEFAULTS)

    # 策略5: 完全降级 — 整段文本当作 visual_summary
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', raw, flags=re.DOTALL)
    cleaned = re.sub(r'^#{1,4}\s*', '', cleaned)
    cleaned = re.sub(r'\*\*', '', cleaned)
    cleaned = re.sub(r'\n+', ' ', cleaned).strip()
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    print(f"    ⚠ VLM JSON 解析失败，降级为纯文本. raw[:100]={raw[:100]}")
    return {**DEFAULTS, "visual_summary": cleaned}


def _try_parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _validate_and_fill(parsed: dict, valid_shots, valid_comp, valid_ang, valid_light, defaults: dict) -> dict:
    """校验字段值，不在合法枚举内的回退为默认值"""
    result = {}
    result["visual_summary"] = str(parsed.get("visual_summary", defaults["visual_summary"]))[:200]
    result["shot_size"] = parsed.get("shot_size", "") if parsed.get("shot_size", "") in valid_shots else defaults["shot_size"]
    result["composition"] = parsed.get("composition", "") if parsed.get("composition", "") in valid_comp else defaults["composition"]
    result["angle"] = parsed.get("angle", "") if parsed.get("angle", "") in valid_ang else defaults["angle"]
    result["emotional_tone"] = str(parsed.get("emotional_tone", defaults["emotional_tone"]))[:20]
    intensity = parsed.get("intensity", defaults["intensity"])
    try:
        result["intensity"] = max(1, min(5, int(intensity)))
    except (ValueError, TypeError):
        result["intensity"] = defaults["intensity"]
    result["lighting"] = parsed.get("lighting", "") if parsed.get("lighting", "") in valid_light else defaults["lighting"]
    actions = parsed.get("actions", defaults["actions"])
    result["actions"] = actions if isinstance(actions, list) else defaults["actions"]
    return result


def _skip_opening_result(idx: int, sm: dict) -> dict:
    """片头段跳过 VLM，直接用 scene_map 信息生成降级结果"""
    return {
        "scene_map_index": idx,
        "start": round(sm["time_range"][0], 2),
        "end": round(sm["time_range"][1], 2),
        "visual_summary": f"{sm.get('location', '')}。{sm.get('event', '')}",
        "shot_size": "中景",
        "composition": "单人",
        "angle": "平视",
        "emotional_tone": sm.get("mood", ""),
        "intensity": 3,
        "lighting": "自然光",
        "actions": [],
        "_tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_chars": [c for c in KNOWN_CHARACTERS if c in sm.get("characters", [])],
    }


# ═══════════════════════════════════ 主流程 ═══════════════════════════════════

def analyze_episode(ep, video_path, segment_duration=10, asr_model="small",
                    skip_vlm=False, skip_asr=False, proxy_res=None):
    work_dir = DRAMA_DIR / "sources" / f"ep{ep}"
    work_dir.mkdir(parents=True, exist_ok=True)

    proxy_label = f" [{proxy_res}p]" if proxy_res else ""
    if proxy_res:
        frames_dir = work_dir / "frames"
        if frames_dir.exists():
            import shutil; shutil.rmtree(frames_dir)

    print(f"\n{'='*60}")
    print(f"EP{ep} 分析: {video_path.name}{proxy_label}")
    print(f"输出: {work_dir}")
    print(f"{'='*60}")

    # [1/5]
    print("\n[1/5] 场景切分")
    scenes = detect_scenes(video_path, work_dir, segment_duration)

    # [2/5]
    if skip_asr:
        asr_segments = json.load(open(work_dir / "asr_result.json"))
        print(f"\n[2/5] ASR (已有): {len(asr_segments)} 段")
    else:
        print("\n[2/5] ASR")
        asr_segments = transcribe_asr(extract_audio(video_path, work_dir), work_dir, asr_model)

    # ── ASR 快速合并 (相邻<2s 合并为完整句) ──
    merged_asr = []
    cur = None
    for seg in asr_segments:
        if cur and seg['start'] - cur['end'] < 2:
            cur['text'] += ' ' + seg['text']
            cur['end'] = seg['end']
        else:
            if cur: merged_asr.append(cur)
            cur = dict(seg)
    if cur: merged_asr.append(cur)
    asr_merged_file = work_dir / "asr_merged.json"
    json.dump(merged_asr, open(asr_merged_file, 'w'), ensure_ascii=False, indent=2)
    print(f"  ASR合并: {len(asr_segments)} → {len(merged_asr)} 句")

    # [3/5]
    print("\n[3/5] Scene Map")
    syn_file = work_dir / "ep_synopsis.json"
    if syn_file.exists():
        synopsis = json.load(open(syn_file)).get('synopsis', '')
        print(f"  synopsis: 已有 ({synopsis[:80]}...)")
    else:
        synopsis = _generate_synopsis(asr_segments, ep)
        if synopsis:
            json.dump({"synopsis": synopsis}, open(syn_file, 'w'), ensure_ascii=False, indent=2)
            print(f"  synopsis: 已生成")
        else:
            print(f"  synopsis: 失败, 使用 ASR-only fallback")
    scene_map = build_scene_map(asr_segments, synopsis, work_dir)

    # [4/5]
    print("\n[4/5] 提取帧")
    frames = extract_frames(video_path, work_dir)
    frame_times = {}
    for f in frames:
        parts = f.stem.split("_")
        if len(parts) == 2 and parts[1].isdigit():
            frame_times[f] = int(parts[1])

    # [5/5] VLM
    # v3: 使用 scene_map 全集（不再跳过前60s），VLM 结果按 scene_map 原始下标存储
    print(f"\n[5/5] VLM ({len(scene_map)} 段)")

    cache_file = work_dir / "vlm_seg_cache_v3.json"
    cache = json.load(open(cache_file)) if cache_file.exists() else {}

    t0 = time.time()
    seg_results = [None] * len(scene_map)
    todo = [i for i in range(len(scene_map)) if str(i) not in cache]

    # 先加载已缓存的条目到 seg_results，确保前情上下文可用
    for i in range(len(scene_map)):
        if str(i) in cache and i not in todo:
            seg_results[i] = cache[str(i)]

    if todo:
        print(f"  待分析: {len(todo)} 段 (串行)")
        for i in todo:
            sm = scene_map[i]
            # 跳过片头 (<60s) 的段：用降级默认值，避免 VLM 浪费在片头
            if sm['time_range'][0] < 60:
                r_clean = _skip_opening_result(i, sm)
                seg_results[i] = r_clean
                cache[str(i)] = r_clean
                json.dump(cache, open(cache_file, 'w'), ensure_ascii=False, indent=2)
                print(f"  [{i}] [skip] 片头段 {sm['time_range']}")
                continue

            try:
                prev = seg_results[i-1].get("visual_summary", "")[:80] if i > 0 and seg_results[i-1] else ""
                r = analyze_segment_vlm(i, sm, frames, frame_times, prev)
                r_clean = {k: v for k, v in r.items() if v is not None}
                seg_results[i] = r_clean
                cache[str(i)] = r_clean
                json.dump(cache, open(cache_file, 'w'), ensure_ascii=False, indent=2)
                chars = r_clean.get("_chars", [])
                expected = set(sm.get('characters', []))
                ok = "ok" if (set(chars) & expected or not expected) else "--"
                desc = r_clean.get("visual_summary", "")[:60]
                tok = r_clean.get("_tokens", {})
                print(f"  [{i}] [{ok}] {desc}... (in:{tok.get('prompt_tokens',0)} out:{tok.get('completion_tokens',0)})")
            except Exception as e:
                print(f"  [{i}] 失败: {e}")
    else:
        seg_results = [cache[str(i)] for i in range(len(scene_map))]
        print(f"  全部复用缓存")

    total_prompt = sum(r.get("_tokens", {}).get("prompt_tokens", 0) for r in seg_results if r)
    total_completion = sum(r.get("_tokens", {}).get("completion_tokens", 0) for r in seg_results if r)
    elapsed = time.time() - t0

    valid = [r for r in seg_results if r and r.get("visual_summary")]
    char_ok = sum(1 for r in valid
                  if set(r.get("_chars", [])) & set(scene_map[r["scene_map_index"]].get("characters", []))
                  or not scene_map[r["scene_map_index"]].get("characters"))

    print(f"\n✅ EP{ep}: {len(scene_map)}段 → VLM {len(valid)}段有效, {len(asr_segments)} ASR")
    print(f"   Token: {total_prompt+total_completion:,} ({elapsed:.0f}s)")
    print(f"   人物: {char_ok}/{len(valid)} ({char_ok/len(valid)*100:.0f}%)" if valid else "")
    return seg_results


def main():
    p = argparse.ArgumentParser(description="EP VLM 分析 v2.3")
    p.add_argument("--ep", default="41")
    p.add_argument("--segment", type=int, default=10)
    p.add_argument("--skip-asr", action="store_true")
    p.add_argument("--skip-vlm", action="store_true")
    p.add_argument("--asr-model", default="small")
    p.add_argument("--proxy", type=int, default=540, choices=[360, 540])
    p.add_argument("--no-proxy", action="store_true")
    args = p.parse_args()

    for ep in [int(e.strip()) for e in args.ep.split(",")]:
        proxy_res = None if args.no_proxy else args.proxy
        video_path = None
        if proxy_res:
            pp = PROXY_DIR / f"都挺好_{ep:02d}_{proxy_res}p.mp4"
            if pp.exists(): video_path = pp
        if not video_path:
            video_path = SRC_VIDEOS / f"都挺好 {ep:02d}_1080p.mp4"
        if not video_path.exists():
            print(f"❌ {video_path}")
            continue
        analyze_episode(ep, video_path, args.segment, args.asr_model,
                        args.skip_vlm, args.skip_asr, proxy_res)


if __name__ == "__main__":
    main()
