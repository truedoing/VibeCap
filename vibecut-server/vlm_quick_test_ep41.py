#!/usr/bin/env python3
"""
VLM 优化版快速测试: EP41 前10分钟(跳过序幕1分钟+落幕3分钟)
改进: 角色参考照+上下文窗口+串行调用
"""
import json, base64, os, sys, re, time
from pathlib import Path
import urllib.request

sys.path.insert(0, '/Users/zgl/VIBECAP/vibecut-server')
from dotenv import load_dotenv
load_dotenv('/Users/zgl/VIBECAP/vibecut-server/.env')

API_KEY = os.environ.get("MIMO_API_KEY", "")
API_URL = "https://api.xiaomimimo.com/v1"
BASE = Path('/Users/zgl/VIBECAP/都挺好')

# 加载数据
with open(BASE / 'sources/ep41/scenes.json') as f: scenes = json.load(f)
with open(BASE / 'sources/ep41/ep_synopsis.json') as f: syn = json.load(f)['synopsis']

frames_dir = BASE / 'sources/ep41/frames'
frame_files = sorted(frames_dir.glob("*.jpg"))

# 用 analyze_episodes.py 的方式提取帧时间: fps=1, 第N帧=N秒
def frame_time(f, index):
    return index + 1  # frame_00001.jpg = 1s

# 角色参考照
portraits_dir = BASE / 'character_portraits'
portrait_b64s = []
for name in ["苏大强","苏明哲","苏明成","苏明玉","朱丽","吴非"]:
    char_dir = portraits_dir / name
    if char_dir.exists():
        for img in sorted(char_dir.glob("*"))[:1]:
            if img.suffix.lower() in ('.png','.jpg','.jpeg'):
                portrait_b64s.append((name, base64.b64encode(img.read_bytes()).decode()))

SKIP_START = 6   # 跳过前1分钟序幕
SKIP_END = 18    # 跳过后3分钟落幕
MAX_SCENES = 60  # 最多60场景=10分钟

results = []
todo = [i for i in range(SKIP_START, min(len(scenes) - SKIP_END, SKIP_START + MAX_SCENES))]

print(f"测试场景: S{SKIP_START}-S{todo[-1]} ({len(todo)}个场景)")
print()

for idx, i in enumerate(todo):
    s = scenes[i]
    start, end = s['start'], s['end']

    # 场景帧: 按时间映射 (fps=1: frame_N = N秒)
    scene_frames = [f for j, f in enumerate(frame_files) if start <= j+1 <= end]
    scene_frames = scene_frames[:min(6, max(3, len(scene_frames)))]

    # 上下文窗口: 前5场景的字幕+人物
    ctx_parts = []
    for j in range(max(0,i-5), i):
        sj = scenes[j]; subs_j = sj.get('subtitles', [])
        prev_chars = results[j-SKIP_START].get('chars', []) if j-SKIP_START >= 0 and j-SKIP_START < len(results) else []
        ctx_parts.append(f"S{j}[{sj['start']:.0f}s]: {'|'.join(subs_j[:2]) or '(无)'} 人物:{prev_chars}")
    ctx_parts.append(f"当前S{i}[{start:.0f}s]: {'|'.join(s.get('subtitles',[])[:3]) or '(无)'}")

    content = []
    for name, b64 in portrait_b64s:
        content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}})
    for f in scene_frames:
        content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{base64.b64encode(f.read_bytes()).decode()}"}})

    prompt = f"参考照:{len(portrait_b64s)}张角色照。本集:{syn}\n上下文:\n{chr(10).join(ctx_parts)}\n\n【人物识别】1.硬字幕称呼词→确定人 2.对比面孔与参考照 3.反推地点。输出:【描述】≤120字【字幕】原文"
    content.append({"type":"text","text":prompt})

    payload = json.dumps({"model":"mimo-v2.5","messages":[{"role":"user","content":content}],"max_tokens":1200}).encode()
    req = urllib.request.Request(f"{API_URL}/chat/completions", data=payload,
        headers={"Content-Type":"application/json","Authorization":f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read())['choices'][0]['message']['content']
    except Exception as e:
        raw = f"ERROR: {e}"

    desc_m = re.search(r'【描述】\n?(.*?)(?:\n【|\n\n|$)', raw)
    desc = desc_m.group(1).strip() if desc_m else raw[:120]

    chars = []
    for c in ['苏大强','苏明哲','苏明成','苏明玉','朱丽','吴非','赵美兰','蔡根花','老聂','石天冬']:
        if c in (desc + raw): chars.append(c)

    subs = s.get('subtitles', [])
    results.append({'sid': i, 'desc': desc, 'chars': chars, 'subs': subs})
    print(f"S{i}[{start:3.0f}s]: {desc}")
    print(f"      字幕:{subs[:3]} 人物:{chars}")
    print()
    time.sleep(0.3)

print(f"完成 {len(results)} 个场景")
