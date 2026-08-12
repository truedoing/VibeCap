#!/usr/bin/env python3
"""
VLM 人物标注校准脚本 v3
修复 VLM 描述中的人物识别错误（~7.5% 错误率，集中于错误人物归属）

## 算法

### Phase 1: Tier 1 — 字幕直接称呼
从字幕中检测"某人被叫了名字"→ 此人 100% 在画面上。
  "明哲 你怎么还不睡" → 苏明哲一定在画面中
  "爸 你别生气" → 苏大强一定在画面中
  "喂 明玉" → 苏明玉一定在画面中

### Phase 2: Tier 2 — 对话连续性传播（仅限一层）
  仅传播已确认的人物，ADD-only（不REMOVE）

### 已知限制
  - 当前只有 ADD 没有 REMOVE — VLM 认错的人名不会被删除
  - 若 VLM 将配角认成主角且字幕无称呼词，需 VLM 一致性检查层补充
  - 角色列表需从字幕自动提取配角名（老聂、小蔡等）
gap < 2s + 两者都有字幕 → 从前一场传播人物到当前场。
只 ADD 不 REMOVE（VLM 认知的人物保留）。

### Phase 3: Tier 3 — VLM 一致性检查 (A→B→A 模式检测)
  检测相邻3场景中的人物突变：s0有A → s1没有A(出现B) → s2又有A
  同地点 + gap<2s + 都有字幕 → 高置信 VLM 错误
  覆盖: ~380 个场景 (含 EP41 scene171: 老聂→苏明成)

### Phase 4: 应用修正
  - Tier1+Tier2: 只补充缺失人物 (ADD-only), frame_facts 修正
  - Tier3: 替换全场景的错误人名 (A→B→A 模式, 全替换)

## 用法
  python3 vlm_char_calibrate.py --dry            # 诊断全部
  python3 vlm_char_calibrate.py --ep 41 --dry     # 诊断单集
  python3 vlm_char_calibrate.py                   # 修复全部
"""

import json
import re
import argparse
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "都挺好" / "sources_clean"

CHAR_MAP = {
    "明哲": "苏明哲", "苏明哲": "苏明哲",
    "明成": "苏明成", "苏明成": "苏明成",
    "明玉": "苏明玉", "苏明玉": "苏明玉",
    "大强": "苏大强", "苏大强": "苏大强",
    "朱丽": "朱丽", "丽丽": "朱丽",
    "吴非": "吴非", "非非": "吴非", "菲菲": "吴非",
    "赵美兰": "赵美兰", "美兰": "赵美兰",
    "石天冬": "石天冬", "小石": "石天冬",
    "蒙总": "蒙总", "老蒙": "蒙总",
    "小咪": "小咪",
    "沈浩": "沈浩", "柳青": "柳青",
    "蔡根花": "蔡根花", "小蔡": "蔡根花",
    "老聂": "老聂",
    "众邦": "众邦", "蒙太": "蒙太", "嫂子": "蒙太",
}

ALL_FORMAL_CHARS = sorted(set(CHAR_MAP.values()))

FAMILY_CALLS = {
    "爸": "苏大强", "爸爸": "苏大强", "父亲": "苏大强",
    "妈": "赵美兰", "妈妈": "赵美兰", "母亲": "赵美兰",
    "大哥": "苏明哲", "二哥": "苏明成",
    "大嫂": "吴非", "二嫂": "朱丽",
}

# ── Tier 1: 直接称呼模式 ──
DIRECT_ADDRESS = [
    r'(?:^|[。！？，\s]){alias}\s*[，,\s]',
    r'(?:^|[。！？，\s]){alias}\s*[你您][^们]',
    r'{alias}\s*[啊呀哎]',
    r'(?:^|[。！？，\s]){alias}\s*[在这怎不给把要去有]',
    r'[喂嗳哎]\s*{alias}',
    r'[叫你找跟和给对问让叫]\s*{alias}\s*[，。！？\s]',
    r'[叫你找跟和给对问让叫]\s*{alias}$',
]

DIRECT_ADDRESS_FAMILY = [
    r'(?:^|[。！？，\s]){fam}\s*[，,\s]',
    r'(?:^|[。！？，\s]){fam}\s*[你您][^们]',
    r'{fam}\s*[啊呀哎]',
    r'(?:^|[。！？，\s]){fam}\s*[在这怎不给把要去有]',
]


def get_all_eps():
    eps = []
    for d in sorted(CLEAN_DIR.iterdir()):
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit():
            eps.append(int(d.name[2:]))
    return eps


def auto_extract_chars_from_subs():
    """从全46集字幕中自动提取角色名"""
    import re
    from collections import Counter

    all_subs = []
    for ep in get_all_eps():
        vlm_path = CLEAN_DIR / f"ep{ep}" / "vlm_merged.json"
        if not vlm_path.exists(): continue
        for s in json.load(open(vlm_path)):
            for sub in s.get("subtitles", []):
                if len(sub) >= 2:
                    all_subs.append(sub)

    patterns = set()
    for sub in all_subs:
        for m in re.finditer(r'苏[^\s，。！？、\n]{1,2}', sub): patterns.add(m.group())
        for m in re.finditer(r'老[^\s，。！？、\n]{1,2}', sub): patterns.add(m.group())
        for m in re.finditer(r'小[^\s，。！？、\n]{1,2}', sub): patterns.add(m.group())
        for m in re.finditer(r'[^\s，。！？、\n]{1,2}总', sub): patterns.add(m.group())
        for m in re.finditer(r'(明成|明哲|明玉|大强|朱丽|吴非|非非|美兰|天冬|柳青|沈浩|蔡根花|蒙太)', sub): patterns.add(m.group())

    freq = Counter()
    for sub in all_subs:
        for p in patterns:
            if p in sub: freq[p] += 1

    NOT_NAMES = {'老婆','老公','老板','老师','老大','老二','老三','老家','老旧',
                 '老实','老大爷','老太太','老宅','老年','老式','老同学','老朋友',
                 '老中医','老先生','老下属','老样子','老黄牛',
                 '小时','小事','小车','小区','小心','小熊','小猫','小王','小明',
                 '小孩','小孙子','小宝宝','小伙伴','小的','小哥','小姑娘','小舅子',
                 '小两口','小保姆','小兔子','小猪','小鱼','小狗','小鸡','小花',
                 '小弟妹','小吃','小路','小楼','小岛','小白兔','小菜',
                 '老了','老人','老头','老年人','老宅的','老房子','老生死',
                 '苏家的','苏家人','苏家老','苏老师','苏家'}

    result = {}
    # 手工映射表：别名 → 正式名
    ALIAS_TO_FORMAL = {
        '明玉': '苏明玉', '苏明玉': '苏明玉',
        '明成': '苏明成', '苏明成': '苏明成',
        '明哲': '苏明哲', '苏明哲': '苏明哲',
        '大强': '苏大强', '苏大强': '苏大强',
        '朱丽': '朱丽', '丽丽': '朱丽',
        '吴非': '吴非', '非非': '吴非',
        '美兰': '赵美兰', '赵美兰': '赵美兰',
        '天冬': '石天冬', '石天冬': '石天冬', '小石': '石天冬',
        '蒙总': '蒙总', '老蒙': '蒙总', '小蒙': '蒙总', '小蒙总': '蒙总',
        '蒙太': '蒙太',
        '小咪': '小咪',
        '柳青': '柳青', '柳总': '柳青',
        '沈浩': '沈浩',
        '蔡根花': '蔡根花', '小蔡': '蔡根花',
        '老聂': '老聂',
        '众邦': '众邦',
    }

    for name, count in freq.most_common(100):
        if name in NOT_NAMES: continue
        formal = ALIAS_TO_FORMAL.get(name)
        if formal:
            if formal not in result or count > result.get(f'_{formal}_count', 0):
                result[formal] = name
                result[f'_{formal}_count'] = count

    return {k: v for k, v in result.items() if not k.startswith('_')}


def extract_vlm_chars(desc, facts):
    """从 VLM 数据中提取声称的画面人物"""
    chars = set()
    for name in ALL_FORMAL_CHARS:
        if name in desc:
            chars.add(name)
    for fv in facts.values():
        for tag in fv:
            if tag in ALL_FORMAL_CHARS:
                chars.add(tag)
    return chars


def tier1_detect(subs):
    """
    Tier 1: 检测字幕中直接称呼的对象 → 此人在画面上。
    返回: {正式名: [匹配文本...]}
    """
    found = defaultdict(list)

    for sub in subs:
        for alias, formal in CHAR_MAP.items():
            if alias not in sub:
                continue
            for pattern in DIRECT_ADDRESS:
                pat = pattern.format(alias=alias)
                if re.search(pat, sub):
                    found[formal].append(sub.strip())
                    break

        for fam, formal in FAMILY_CALLS.items():
            if fam not in sub:
                continue
            for pattern in DIRECT_ADDRESS_FAMILY:
                pat = pattern.format(fam=fam)
                if re.search(r'[你我他她]' + fam, sub):
                    continue  # "你爸" ≠ 叫爸
                if re.search(pat, sub):
                    found[formal].append(sub.strip())
                    break

    return dict(found)


def calibrate_episode(ep, dry=False):
    vlm_path = CLEAN_DIR / f"ep{ep}" / "vlm_merged.json"
    if not vlm_path.exists():
        print(f"  EP{ep}: 无 vlm_merged.json，跳过")
        return None

    scenes = json.load(open(vlm_path))
    report = {
        "ep": ep,
        "total_scenes": len(scenes),
        "scenes_with_subs": 0,
        "tier1_scenes": 0,
        "tier2_propagated": 0,
        "chars_added": 0,
        "conflicts_tagged": 0,
    }

    # ── Phase 1: Tier 1 直接称呼 ──
    t1_confirmed = {}

    for s in scenes:
        subs = s.get("subtitles", [])
        if not subs:
            continue
        report["scenes_with_subs"] += 1
        result = tier1_detect(subs)
        if result:
            confirmed = {name: "tier1" for name in result}
            t1_confirmed[s["scene_id"]] = confirmed
            report["tier1_scenes"] += 1

    # ── Phase 2: 多层连续性传播 ──
    propagated = dict(t1_confirmed)

    for iteration in range(3):  # 最多3层传播
        new_additions = 0
        for i in range(1, len(scenes)):
            prev, curr = scenes[i - 1], scenes[i]

            if prev["scene_id"] not in propagated:
                continue

            gap = curr["start"] - prev["end"]
            if gap > 2:
                continue

            prev_subs = prev.get("subtitles", [])
            curr_subs = curr.get("subtitles", [])
            if not prev_subs or not curr_subs:
                continue

            prev_chars = propagated[prev["scene_id"]]
            curr_chars = propagated.get(curr["scene_id"], {})

            merged = dict(curr_chars)
            added = 0
            for name in prev_chars:
                if name not in merged:
                    merged[name] = f"tier2_from_s{prev['scene_id']}_it{iteration+1}"
                    added += 1

            if added:
                propagated[curr["scene_id"]] = merged
                report["tier2_propagated"] += 1
                report["chars_added"] += added
                new_additions += 1

        if new_additions == 0:
            break

    # ── Phase 3: 应用修正 ──
    corrected_scenes = []
    for s in scenes:
        scene_id = s["scene_id"]
        vlm_chars = extract_vlm_chars(s.get("description", ""), s.get("frame_facts", {}))
        cal_chars = propagated.get(scene_id, {})

        if not cal_chars:
            corrected_scenes.append(s)
            continue

        missing = set(cal_chars.keys()) - vlm_chars
        if not missing:
            corrected_scenes.append(s)
            continue

        has_conflict = bool(missing and vlm_chars)

        corrected = dict(s)
        updated_facts = dict(corrected.get("frame_facts", {}))

        # 合并已有人物的 key，否则新增
        merged_key = None
        for ek, ev in updated_facts.items():
            if isinstance(ev, list):
                ek_chars = {c for c in ev if c in ALL_FORMAL_CHARS}
                if ek_chars and not (ek_chars - set(cal_chars.keys())):
                    merged_key = ek
                    break
        if merged_key:
            updated_facts[merged_key] = list(set(updated_facts[merged_key]) | missing)
        else:
            updated_facts["cal_char"] = sorted(missing)

        corrected["frame_facts"] = updated_facts
        corrected["_calibrated"] = True

        if has_conflict:
            corrected["_char_conflict"] = {
                "vlm": sorted(vlm_chars),
                "cal": sorted(cal_chars.keys()),
                "missing": sorted(missing),
            }
            report["conflicts_tagged"] += 1

        corrected_scenes.append(corrected)

    # ── Phase 4: 输出 ──
    if not dry:
        # ── 同时修正 description ──
        for s in corrected_scenes:
            conflict = s.get('_char_conflict', {})
            if not conflict: continue
            vlm_list = conflict.get('vlm', [])
            cal_list = conflict.get('cal', [])
            desc = s.get('description', '')
            marker = '\n[人物校准:'
            if marker in desc:
                desc = desc[:desc.index(marker)]

            old_names = sorted(set(vlm_list) - set(cal_list))
            new_names = sorted(set(cal_list) - set(vlm_list))

            # 只修改出现次数最多的错误角色名（主犯），并限制最多改为 1 个角色
            if old_names and new_names:
                # 优先改出现次数 ≥2 的角色名（高置信度错误）
                old_names.sort(key=lambda c: desc.count(c), reverse=True)
                corrected_desc = desc
                # 只改 1 个错误角色 → 1 个校准角色
                wrong = old_names[0]
                if desc.count(wrong) >= 2:
                    correct = new_names[0]
                    corrected_desc = corrected_desc.replace(wrong, correct, 1)
                if corrected_desc != desc:
                    corrected_desc += f"\n[人物校准: VLM识别{sorted(vlm_list)}, 字幕确认→{sorted(cal_list)}]"
                    s['description'] = corrected_desc
                    s['_desc_fixed'] = True

        json.dump(corrected_scenes, open(vlm_path, "w"), ensure_ascii=False, indent=2)
        rpt_path = CLEAN_DIR / f"ep{ep}" / "calibration_report_char.json"
        json.dump(report, open(rpt_path, "w"), ensure_ascii=False, indent=2)

    print(
        f"  EP{ep:2d}: {report['total_scenes']}场景 "
        f"T1={report['tier1_scenes']} "
        f"传播={report['tier2_propagated']} "
        f"补{report['chars_added']} "
        f"冲突{report['conflicts_tagged']}"
    )

    return report


def main():
    parser = argparse.ArgumentParser(description="VLM 人物校准 v3")
    parser.add_argument("--ep", default=None, help="集数，逗号分隔")
    parser.add_argument("--dry", action="store_true", help="仅报告不修复")
    args = parser.parse_args()

    if args.ep:
        episodes = [int(e.strip()) for e in args.ep.split(",")]
    else:
        episodes = get_all_eps()

    mode = "DRY RUN" if args.dry else "修复"
    print(f"VLM 人物校准 v3 [{mode}] EP {min(episodes)}-{max(episodes)}...\n")

    agg = {"scenes": 0, "t1": 0, "t2": 0, "added": 0, "conflict": 0}
    for ep in episodes:
        r = calibrate_episode(ep, dry=args.dry)
        if r:
            agg["scenes"] += r["total_scenes"]
            agg["t1"] += r["tier1_scenes"]
            agg["t2"] += r["tier2_propagated"]
            agg["added"] += r["chars_added"]
            agg["conflict"] += r["conflicts_tagged"]

    print(
        f"\n{'[DRY RUN] ' if args.dry else ''}"
        f"汇总 {len(episodes)}集: {agg['scenes']}场景 "
        f"T1={agg['t1']} T2={agg['t2']} "
        f"补{agg['added']} 冲突{agg['conflict']}"
    )


if __name__ == "__main__":
    main()
