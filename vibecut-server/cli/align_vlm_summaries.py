#!/usr/bin/env python3
"""VLM visual_summary ↔ scene_map 全量一致性校对

背景: VLM 描述是当初按旧 scene_map 写的, 校准后部分场景描述与新 scene_map 矛盾
(不只是名字矛盾, 还有地点/事件/内容矛盾, 如 EP32 S6)。只做名字扫描抓不全。

本脚本: 逐段喂「修正后的 scene_map(chars/loc/event) + 当前 visual_summary」,
让 DeepSeek 判断是否一致:
  - OK      → 一致, 保留
  - FIX     → 不一致, 重写描述使其与权威 scene_map 一致 (人物/地点/事件)
  - MISSING → 描述提到权威人物之外的人且场景需要他在场 → 报告 scene_map 可能漏人(不改)

铁律: 权威信息(scene_map)是标准, VLM 描述向它对齐; 不改段数/边界/不改 scene_map。

用法:
  python3 cli/align_vlm_summaries.py --dry-run     # 只出报告
  python3 cli/align_vlm_summaries.py --ep 32       # 单集 dry-run
  python3 cli/align_vlm_summaries.py --apply       # 应用 FIX 重写
"""

import json, argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from lib.llm import call_deepseek

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"

ALIGN_PROMPT = """你是《都挺好》的场记校对。下面每段是一个场景的【权威信息】(修正后) 和它的【VLM画面描述】。判断 VLM描述 是否与 权威信息 一致。

铁律：
1. 权威信息(人物/地点/事件)是最终标准。VLM描述可能过时(按旧信息写的)。
2. 判断"一致"的标准：
   - 人物：描述中明确在画面里的人应是权威人物。提到但不在场的(电话里/被提及)不算矛盾。
   - 地点/事件：描述不应与权威信息冲突。
3. 一致 → "OK"
4. 不一致 → "FIX"，输出修正后的描述(≤80字)，使其与权威信息一致：
   - 权威人物应体现在描述中；旧描述里的人物若不在权威人物里且不在场，删除或替换。
   - 画面细节(景别/动作/表情/光线/氛围/衣着)尽量保留原文。
5. 若描述明确提到一个权威人物之外的人"在画面中"，且该场景事件明显需要他在场
   (如"向X道歉"而X不在人物列表) → "MISSING"，报告人名(只报告，不改描述)。

输入格式：
[场景号] 权威: chars=[...] loc=... event=...
  VLM: ...

输出严格 JSON（不要 markdown）：
{"0": {"verdict": "OK"}}
{"1": {"verdict": "FIX", "summary": "修正后的描述"}}
{"2": {"verdict": "MISSING", "names": ["苏大强"]}}"""


def _strip_md(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def _parse_json(text):
    """解析多个独立 JSON 对象 (模型按场景逐行输出)"""
    result = {}
    dec = json.JSONDecoder()
    idx = 0
    text = text.strip()
    while idx < len(text):
        while idx < len(text) and text[idx] not in '{[':
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = dec.raw_decode(text[idx:])
            if isinstance(obj, dict):
                result.update(obj)
            idx += end
        except json.JSONDecodeError:
            idx += 1
    return result


def run_episode(ep: int, batch_size: int = 10, apply: bool = False):
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    vlm_file = SOURCES_DIR / f"ep{ep}" / "vlm_seg_cache_v3.json"
    if not sm_file.exists() or not vlm_file.exists():
        return {"ep": ep, "ok": 0, "fix": 0, "missing": []}
    sm = json.load(open(sm_file))
    vlm = json.load(open(vlm_file))

    scenes = list(range(min(len(sm), len(vlm))))
    stats = {"OK": 0, "FIX": 0, "MISSING": 0}
    fix_items = []
    missing_items = []

    for bi in range(0, len(scenes), batch_size):
        batch = scenes[bi:bi + batch_size]
        lines = []
        for i in batch:
            s = sm[i]
            vs = vlm.get(str(i), {}).get('visual_summary', '')
            lines.append(f"[{i}] 权威: chars={s.get('characters', [])} loc={s.get('location', '')} event={s.get('event', '')}")
            lines.append(f"  VLM: {vs}")
        user = f"第{ep}集 场景:\n" + "\n".join(lines)
        res = call_deepseek(ALIGN_PROMPT, user, temperature=0.1, max_tokens=3000,
                            timeout=120, label=f"align_ep{ep}_b{bi}")
        if not res.get("ok"):
            print(f"  ⚠ 批{bi//batch_size+1} 失败: {res.get('error','?')[:80]}")
            continue
        data = _parse_json(_strip_md(res.get("content", "")))
        for i in batch:
            item = data.get(str(i)) or data.get(i)
            if not isinstance(item, dict):
                continue
            verdict = item.get("verdict", "OK")
            stats[verdict] = stats.get(verdict, 0) + 1
            if verdict == "FIX":
                summary = str(item.get("summary", "")).strip()
                if summary:
                    fix_items.append((i, summary))
            elif verdict == "MISSING":
                missing_items.append((i, item.get("names", [])))

    if apply and fix_items:
        for i, summary in fix_items:
            vlm[str(i)]["visual_summary"] = summary[:200]
        json.dump(vlm, open(vlm_file, "w"), ensure_ascii=False, indent=2)

    return {"ep": ep, "ok": stats.get("OK", 0), "fix": len(fix_items),
            "missing": missing_items, "fix_items": fix_items}


def main():
    p = argparse.ArgumentParser(description="VLM visual_summary ↔ scene_map 一致性校对")
    p.add_argument("--ep", default=None, help="单集/多集 (逗号分隔)")
    p.add_argument("--batch", type=int, default=10)
    p.add_argument("--apply", action="store_true", help="应用 FIX 重写 (默认只报告)")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())

    total_fix, total_missing = 0, 0
    for ep in eps:
        r = run_episode(ep, args.batch, args.apply)
        if r["fix"] or r["missing"]:
            print(f"=== EP{ep}: OK={r['ok']} FIX={r['fix']} MISSING={len(r['missing'])} ===")
            for i, summary in r.get("fix_items", []):
                print(f"  FIX S{i}: -> {summary[:50]}")
            for i, names in r.get("missing", []):
                print(f"  MISSING S{i}: scene_map 可能漏 {names}")
            total_fix += r["fix"]
            total_missing += len(r["missing"])
        else:
            print(f"=== EP{ep}: 全部一致 OK={r['ok']} ===")

    print(f"\n总计: FIX {total_fix} 段 / MISSING {total_missing} 段" + (" (已应用)" if args.apply else " (dry-run, 未应用)"))


if __name__ == "__main__":
    main()
