#!/usr/bin/env python3
"""scene_map 逐场景校准 — 独立重推 + diff（去掉确认偏误）

背景: scene_map.json 是每集一次性让 DeepSeek 从「30秒文本团」推断生成的，
存在错标 (人物/地点/事件与字幕不符)。直接拿现有标注让模型核对会有「确认偏误」
(模型倾向复读标注, 测试证明抓不到 S5/S11)。

本脚本: 独立重推模式 —— 不给模型看现有标注，只给「该场景窗口的逐句字幕(带时间戳)」，
让 DeepSeek 独立推断 characters/location/event，再与现有 scene_map diff。

铁律:
  - 绝不改 time_range，绝不增删场景 (遵守 scene_map 分段锁死铁律)
  - characters 只收「画面上实际在场的人」——电话里/被提及的人不收
  - 无有效对话的段 (背景音乐歌词/静默) → no_dialogue，跳过不改

用法:
  python3 cli/calibrate_scene_map.py --ep 32              # 单集 diff (dry-run)
  python3 cli/calibrate_scene_map.py --ep 32 --apply       # 应用修正 (先备份)
  python3 cli/calibrate_scene_map.py                       # 全部 46 集
  python3 cli/calibrate_scene_map.py --ep 32 --batch 6     # 每批场景数
"""

import json, argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # cli/ → vibecut-server/

from lib.llm import call_deepseek

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
DRAMA_DIR = BASE_DIR / "都挺好"
SOURCES_DIR = DRAMA_DIR / "sources"

DERIVE_PROMPT = """你是《都挺好》的场记。根据每段戏的逐句字幕（带时间戳），独立推断这段戏的实际内容。你【没有】任何已有标注，全靠字幕判断。

铁律：
1. characters = 画面上实际在场的人。电话里/被提到/回忆的人【不在场】，不收。
   例：字幕说「打电话给明哲」→ 明哲只在电话里，不在场。
2. location = 这段戏实际发生的地点，从对话内容推断（不要默认填某个地点）。
3. event = 这段戏实际发生的事（≤20字）。
4. 人物用标准全名（ASR误识纠正：朱莉→朱丽、宋明成→苏明成、小菜→小蔡）：
   苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡/老聂，以及本剧配角（周姐/柳青/小咪/蒙总/老聂/朱丽母亲/朱丽父亲/苏母/石天冬/刘总/小金 等）。
5. 若这段戏几乎没有有效对话（只有背景音乐歌词/纯静默）→ 输出 "no_dialogue": true，不强行推断。

输入格式：
[场景号] [start-end秒]
  字幕[start秒]: 台词
  字幕[start秒]: 台词

输出严格 JSON（不要 markdown）：
{"0": {"characters": ["苏明玉"], "location": "苏家老宅", "event": "苏明玉质问苏大强"}, ...}
无有效对话的场景用 {"5": {"no_dialogue": true}}"""


def _window_subs(subs, a, b):
    return [(s['start'], s['end'], s['text']) for s in subs if s['start'] >= a and s['start'] < b]


def _strip_md(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def _parse_json(text: str) -> dict:
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _bigrams(s: str) -> set:
    s = s.replace(' ', '')
    return {s[i:i+2] for i in range(len(s) - 1)}


def _event_overlap(a: str, b: str) -> float:
    """两个事件的字符 bigram 重叠率 (0-1)"""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def derive_episode(ep: int, batch_size: int = 6) -> tuple:
    """独立重推 → (derived: {idx: {...}}, scene_map, subs)"""
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    scene_map = json.load(open(sm_file))
    sub_file = SOURCES_DIR / f"ep{ep}" / "subtitle_result.json"
    subs = json.load(open(sub_file))

    derived = {}
    for start in range(0, len(scene_map), batch_size):
        batch = []
        for j in range(start, min(start + batch_size, len(scene_map))):
            s = scene_map[j]
            w = _window_subs(subs, *s['time_range'])
            if w:
                batch.append((j, s, w))
        if not batch:
            continue
        lines = []
        for j, s, w in batch:
            lines.append(f"[{j}] [{s['time_range'][0]}-{s['time_range'][1]}s]")
            for st, en, t in w:
                lines.append(f"  字幕[{st:.0f}s]: {t}")
        user = f"第{ep}集 场景(批次{start//batch_size+1}):\n" + "\n".join(lines)
        res = call_deepseek(DERIVE_PROMPT, user, temperature=0.1, max_tokens=2000,
                            timeout=120, label=f"derive_ep{ep}_b{start//batch_size+1}")
        if not res.get("ok"):
            print(f"  ⚠ 批次{start//batch_size+1} 调用失败: {res.get('error','?')[:80]}")
            continue
        data = _parse_json(_strip_md(res.get("content", "")))
        for k, v in data.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(scene_map) and isinstance(v, dict):
                derived[idx] = v
    return derived, scene_map, subs


def build_diff(ep: int, derived: dict, scene_map: list) -> list:
    """对比 derived vs stored → 变更列表 [{idx, chars_changed, loc_changed, ev_changed, ...}]"""
    diffs = []
    for i, s in enumerate(scene_map):
        d = derived.get(i)
        if d is None:
            continue
        if d.get("no_dialogue"):
            diffs.append({"idx": i, "skip": "no_dialogue", "stored": s})
            continue
        d_chars = [str(c).strip() for c in (d.get("characters") or [])]
        d_loc = str(d.get("location", "")).strip()
        d_ev = str(d.get("event", "")).strip()
        chars_changed = set(d_chars) != set(s.get("characters", []))
        loc_changed = d_loc != s.get("location", "")
        ev_changed = _event_overlap(d_ev, s.get("event", "")) < 0.3
        if chars_changed or loc_changed or ev_changed:
            diffs.append({
                "idx": i,
                "skip": None,
                "stored": s,
                "derived": {"characters": d_chars, "location": d_loc, "event": d_ev},
                "chars_changed": chars_changed,
                "loc_changed": loc_changed,
                "ev_changed": ev_changed,
            })
    return diffs


# 人物名字形式 (用于「字幕坐实」判定)
NAME_FORMS = {
    '苏大强': ['苏大强', '大强'],
    '苏明哲': ['苏明哲', '明哲'],
    '苏明成': ['苏明成', '明成'],
    '苏明玉': ['苏明玉', '明玉'],
    '朱丽': ['朱丽', '丽丽'],
    '吴非': ['吴非', '非非'],
    '小蔡': ['小蔡'],
    '老聂': ['老聂'],
}


def _name_grounded(name: str, window_text: str) -> bool:
    """判断一个人名是否被该窗口字幕「坐实」(名字/昵称/亲属称谓出现)"""
    for form in NAME_FORMS.get(name, [name]):
        if form in window_text:
            return True
    # 亲属称谓: 朱丽母亲/朱丽父亲/苏母 等
    if '母' in name and ('妈' in window_text or '母亲' in window_text):
        return True
    if '父' in name and ('爸' in window_text or '父亲' in window_text):
        return True
    return False


def apply_rules(stored: dict, derived: dict, window_text: str) -> dict:
    """人物优先的保守应用规则

    优先级: 人物准确率 > 地点/事件。

    自动应用(安全):
      - 子集删人: 重推是现有标注的子集 → 纯删人, 治"多编造人物"(分镜匹配错人的主因)
    需人工确认:
      - 整段替换: 重推与现有标注完全不同 且 被字幕坐实 (如 S5) → 人物/地点/事件一起改,
        但因 LLM 随机性, 替换身份可能漂移, 需人核对
    跳过:
      - 加人(超集): 可能幻觉, 不做
      - 替换未坐实: 不可信, 不做
      - 地点/事件单独变更: 不做自动应用(地点推断不可靠), 仅报告
    """
    stored_chars = set(stored.get('characters', []))
    der_chars = set(derived.get('characters', []))

    if der_chars == stored_chars:
        return {"action": "keep", "reason": "人物一致"}

    # 子集删人 → 自动应用 (但 event/location 提到的人不删, 避免自相矛盾)
    if der_chars and der_chars < stored_chars:
        ref_text = stored.get('event', '') + stored.get('location', '')
        kept_by_ref = {c for c in (stored_chars - der_chars) if c in ref_text}
        if kept_by_ref:
            final = sorted(der_chars | kept_by_ref)
            if set(final) == stored_chars:
                return {"action": "keep", "reason": f"删人但event提及 {kept_by_ref}, 保守保留"}
            return {"action": "apply_chars", "reason": f"删人(保留event提及 {kept_by_ref})", "characters": final}
        return {"action": "apply_chars", "reason": f"子集删人 {stored_chars - der_chars}",
                "characters": sorted(der_chars)}

    # 加人(超集) → 跳过
    if der_chars and der_chars > stored_chars:
        return {"action": "skip", "reason": f"超集加人 {der_chars - stored_chars} (可能幻觉, 不做)"}

    # 整段替换 → 需人工确认
    if all(_name_grounded(c, window_text) for c in der_chars):
        return {"action": "review", "reason": "整段替换(被字幕坐实), 需人工确认",
                "characters": sorted(der_chars),
                "location": derived.get('location', ''),
                "event": derived.get('event', '')}

    return {"action": "skip", "reason": "替换未被字幕坐实, 不做"}


def apply_diffs(ep: int, diffs: list, scene_map: list, subs: list) -> dict:
    """按人物优先规则应用 → {applied, review, skipped, n}"""
    applied, review, skipped = [], [], []
    for d in diffs:
        if d.get("skip"):
            skipped.append({"idx": d["idx"], "reason": "no_dialogue"})
            continue
        idx = d["idx"]
        stored = scene_map[idx]
        derived = d["derived"]
        a, b = stored['time_range']
        window_text = ' '.join(t for _, _, t in _window_subs(subs, a, b))
        r = apply_rules(stored, derived, window_text)
        if r["action"] == "apply_chars":
            stored["characters"] = r["characters"]
            applied.append({"idx": idx, "reason": r["reason"],
                            "from": stored.get('characters'), "to": r["characters"]})
        elif r["action"] == "review":
            review.append({"idx": idx, "reason": r["reason"],
                           "stored": {"characters": stored.get('characters'),
                                      "location": stored.get('location', ''),
                                      "event": stored.get('event', '')},
                           "candidate": {"characters": r["characters"],
                                         "location": r["location"], "event": r["event"]}})
        else:
            skipped.append({"idx": idx, "reason": r["reason"]})
    if applied:
        sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
        json.dump(scene_map, open(sm_file, "w"), ensure_ascii=False, indent=2)
    return {"applied": applied, "review": review, "skipped": skipped,
            "n": len(applied)}


def main():
    p = argparse.ArgumentParser(description="scene_map 人物优先校准 (独立重推 + diff)")
    p.add_argument("--ep", default=None, help="单集/多集 (逗号分隔)")
    p.add_argument("--batch", type=int, default=6, help="每批场景数 (默认6)")
    p.add_argument("--apply", action="store_true", help="自动应用安全修正 (子集删人)")
    p.add_argument("--confirm", default=None, help="确认整段替换 (逗号分隔的场景号, 如 5,24)")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())

    for ep in eps:
        print(f"\n=== EP{ep} ===")
        derived, scene_map, subs = derive_episode(ep, args.batch)
        diffs = build_diff(ep, derived, scene_map)
        changes = [d for d in diffs if not d.get("skip")]

        if args.apply:
            r = apply_diffs(ep, diffs, scene_map, subs)
            print(f"  ✅ 自动应用 {r['n']} 段 (子集删人)")
            for a in r["applied"]:
                print(f"     S{a['idx']} {a['reason']}: {a['from']} -> {a['to']}")
            print(f"  ⏳ 需人工确认 {len(r['review'])} 段 (整段替换):")
            for v in r["review"]:
                st, ca = v["stored"], v["candidate"]
                print(f"     S{v['idx']}: 现={st['characters']}@{st['location']} | 候选={ca['characters']}@{ca['location']} | {ca['event']}")
            print(f"  ⏭ 跳过 {len(r['skipped'])} 段")
            for s in r["skipped"]:
                if s.get("reason") != "no_dialogue":
                    print(f"     S{s['idx']}: {s['reason']}")

            # --confirm: 确认后应用整段替换
            if args.confirm and r["review"]:
                confirm_set = {int(x) for x in args.confirm.split(",") if x.strip().isdigit()}
                applied_c = 0
                for v in r["review"]:
                    if v["idx"] in confirm_set:
                        s = scene_map[v["idx"]]
                        ca = v["candidate"]
                        s["characters"] = ca["characters"]
                        s["location"] = ca["location"]
                        s["event"] = ca["event"]
                        applied_c += 1
                        print(f"     ✅ 已确认 S{v['idx']}: -> {ca['characters']}@{ca['location']} | {ca['event']}")
                if applied_c:
                    json.dump(scene_map, open(SOURCES_DIR / f"ep{ep}" / "scene_map.json", "w"),
                              ensure_ascii=False, indent=2)
            continue

        print(f"  重推 {len(derived)} 段 / 与标注人物不一致 {len(changes)} 段 / no_dialogue {len([d for d in diffs if d.get('skip')])} 段")
        for d in changes:
            s, der = d["stored"], d["derived"]
            print(f"  S{d['idx']} [人物/地点/事件]:")
            print(f"    现: {s.get('characters')} @ {s.get('location')} | {s.get('event')}")
            print(f"    重推: {der['characters']} @ {der['location']} | {der['event']}")


if __name__ == "__main__":
    main()
