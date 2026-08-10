#!/usr/bin/env python3
"""
Tier 4 — LLM 对话链推理校准 v2 (DeepSeek + 人物关系图谱)
优化: 角色关系从字幕自动提取, 减少API调用, 提高准确率

用法:
  python3 vlm_char_calibrate_t4.py --dry           # 诊断候选
  python3 vlm_char_calibrate_t4.py --ep 41 --dry    # 诊断单集
  python3 vlm_char_calibrate_t4.py                  # 全量校准
"""

import json, os, sys, time, re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "都挺好" / "sources_clean"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.llm import call_deepseek_json

ALL_CHARS = [
    '苏明哲', '苏明成', '苏明玉', '苏大强', '朱丽', '吴非',
    '赵美兰', '蔡根花', '石天冬', '蒙总', '蒙太', '小咪',
    '众邦', '沈浩', '柳青', '老聂'
]

CALL_NAMES = {'明哲','明成','明玉','大强','朱丽','吴非','美兰','天冬','蒙总','小咪','老聂','蔡根花'}

SYSTEM_PROMPT = """你是电视剧《都挺好》的角色推断专家。
已知角色关系(从全46集字幕自动提取):
- 苏大强 = 父亲(苏明哲/苏明成/苏明玉的父亲)，妻赵美兰已故，保姆蔡根花
- 苏明哲 = 大哥，苏大强的长子，和吴非是夫妻，住在美国
- 苏明成 = 二哥，苏大强的次子，和朱丽是夫妻
- 苏明玉 = 小妹，苏大强的女儿
- 吴非 = 大嫂(苏明哲的妻子)
- 朱丽 = 二嫂(苏明成的妻子)
- 赵美兰 = 已故母亲(苏家三兄妹的母亲)，苏大强的亡妻
- 蔡根花 = 保姆(苏大强要娶的对象)
- 老聂 = 苏大强的老朋友
- 石天冬 = 苏明玉的男友
- 小咪 = 苏明哲与吴非的女儿
- 蒙总/老蒙 = 苏明玉的老板
- 众邦 = 舅舅
- 蒙太 = 蒙总的妻子

亲属称呼推断规则:
- "咱爸" → 说话者与听者有共同的父亲(苏大强)，都是苏家子女
- "大哥" → 听者是苏明哲
- "大嫂" → 听者是吴非
- "二哥" → 听者是苏明成
- "二嫂" → 听者是朱丽
- "咱妈" → 共同的母亲(已故的赵美兰)
- "我爸" → 说话者是苏家子女之一(参考上面)
- 场景如果讨论苏大强要结婚 → 子女或老聂在画面上

输出JSON格式: {"scene_编号": ["角色名",...], ...}
注意: 只输出JSON, 不要任何解释文字。"""


def get_all_eps():
    eps = []
    for d in sorted(CLEAN_DIR.iterdir()):
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit():
            eps.append(int(d.name[2:]))
    return eps


def extract_dialogue_segments(scenes):
    """提取连续对话段 (gap<2s, 都有字幕, 含称呼词)"""
    segments = []
    i = 0
    while i < len(scenes):
        s = scenes[i]
        if not s.get('subtitles'):
            i += 1; continue
        start_i = i
        while i+1 < len(scenes) and scenes[i+1]['start']-scenes[i]['end']<2 and scenes[i+1].get('subtitles'):
            i += 1
        if start_i < i:
            all_subs = []
            for j in range(start_i, i+1):
                all_subs.extend(scenes[j].get('subtitles', []))
            if any(any(name in sub for name in CALL_NAMES) for sub in all_subs):
                segments.append([scenes[j] for j in range(start_i, i+1)])
        i += 1
    return segments


def calibrate_ep_t4(ep, dry=False):
    vlm_path = CLEAN_DIR / f"ep{ep}" / "vlm_merged.json"
    if not vlm_path.exists():
        return None

    scenes = json.load(open(vlm_path))
    segments = extract_dialogue_segments(scenes)

    # 只处理含未校准场景的段
    need_cal = []
    for seg in segments:
        has_uncalibrated = False
        for s in seg:
            if not s.get('_calibrated') and not s.get('_tier3_fixed'):
                if [c for c in ALL_CHARS if c in s.get('description', '')]:
                    has_uncalibrated = True; break
        if has_uncalibrated:
            need_cal.append(seg)

    if not need_cal:
        return {"ep": ep, "segments_processed": 0, "scenes_fixed": 0}

    fixed_count = 0
    for seg in need_cal:
        if dry:
            fixed_count += len(seg)
            continue

        # 构建精简 prompt
        lines = [f"scene_{s['scene_id']} [{s['start']:.0f}s]: 字幕={'|'.join(s['subtitles'][:3])}"
                 for s in seg]
        prompt = '\n'.join(lines)

        result = call_deepseek_json(
            SYSTEM_PROMPT,
            f"对话链，推断每个场景中实际在画面中的角色:\n\n{prompt}",
            max_tokens=150, temperature=0.0,
            label=f"EP{ep}S{seg[0]['scene_id']}"
        )

        if not result.get("ok"):
            continue

        llm_data = result.get("data", {})
        if not isinstance(llm_data, dict):
            continue

        for s in seg:
            key = f"scene_{s['scene_id']}"
            llm_chars = llm_data.get(key, [])
            if not llm_chars:
                for k, v in llm_data.items():
                    if str(s['scene_id']) in k: llm_chars = v; break
            if not isinstance(llm_chars, list) or not llm_chars:
                continue

            desc = s['description']
            marker = '\n[人物校准:'
            if marker in desc: desc = desc[:desc.index(marker)]

            vlm_set = {c for c in ALL_CHARS if c in desc}
            llm_set = set(llm_chars)
            if vlm_set == llm_set:
                continue

            to_remove = vlm_set - llm_set
            to_add = llm_set - vlm_set
            corrected = desc
            for wrong in sorted(to_remove, key=lambda c: desc.count(c), reverse=True):
                for correct in sorted(to_add):
                    if wrong in corrected:
                        corrected = corrected.replace(wrong, correct, 1)
                        to_add.discard(correct)
                        break
            corrected += f"\n[人物校准: VLM识别{sorted(vlm_set)}, LLM推断→{sorted(llm_set)}]"
            s['description'] = corrected
            s['_t4_fixed'] = True
            fixed_count += 1

            facts = s.get('frame_facts', {})
            for k in list(facts.keys()):
                if isinstance(facts[k], list):
                    facts[k] = [llm_chars[0] if x in to_remove else x for x in facts[k]]
            if to_add:
                facts['t4_char'] = sorted(to_add)
            s['frame_facts'] = facts

        time.sleep(0.05)

    if not dry and fixed_count > 0:
        json.dump(scenes, open(vlm_path, 'w'), ensure_ascii=False, indent=2)

    print(f"  EP{ep}: {len(need_cal)}段 {fixed_count}修正", flush=True)
    return {"ep": ep, "segments_processed": len(need_cal), "scenes_fixed": fixed_count}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="T4 LLM 校准 v2")
    parser.add_argument("--ep", default=None, help="集数,逗号分隔")
    parser.add_argument("--dry", action="store_true", help="仅诊断")
    args = parser.parse_args()

    episodes = [int(e.strip()) for e in args.ep.split(",")] if args.ep else get_all_eps()

    mode = "DRY RUN" if args.dry else "校准"
    print(f"T4 v2 [{mode}] EP {min(episodes)}-{max(episodes)}...\n")

    total_seg, total_fixed = 0, 0
    for ep in episodes:
        r = calibrate_ep_t4(ep, dry=args.dry)
        if r:
            total_seg += r["segments_processed"]
            total_fixed += r["scenes_fixed"]

    print(f"\n{'[DRY RUN] ' if args.dry else ''}"
          f"汇总: {len(episodes)}集 {total_seg}段 {total_fixed}修正")


if __name__ == "__main__":
    main()
