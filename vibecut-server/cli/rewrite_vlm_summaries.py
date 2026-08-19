#!/usr/bin/env python3
"""VLM visual_summary 对齐重写 — 只改人物/事件，保留画面细节

背景: scene_map 校准后, 部分场景的 VLM visual_summary 还是按旧 scene_map 写的
(旧描述里出现被删/被换的人名), 与新 scene_map 矛盾。

本脚本: 对「旧描述含被删/换人名」的段, 用 DeepSeek 按修正后的 characters/location/event
纯文本重写 visual_summary (不重新调 MiMo VLM, 不碰画面)。

约束:
  - 只改人物身份 + 事件, 画面细节(景别/动作/表情/光线/氛围)保持原文
  - 只重写矛盾段, 其余段的原始 VLM 描述原样保留
  - 不改变段数/时间边界 (VLM 缓存按下标对齐不变)

用法:
  python3 cli/rewrite_vlm_summaries.py --ep 32
  python3 cli/rewrite_vlm_summaries.py --dry-run
  python3 cli/rewrite_vlm_summaries.py
"""

import json, argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from lib.llm import call_deepseek

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"

REWRITE_PROMPT = """你是《都挺好》的场记。以下是某场景的【旧画面描述】和【修正后的权威信息】。

你的任务：重写画面描述，使其与修正后的权威信息一致。

★ 铁律：
1. 人物身份：旧描述里出现的、但不在权威人物中的人 → 删除，或换成权威人物。权威人物应体现在描述中。
2. 事件：描述要与修正后的事件一致。
3. 画面细节（地点/景别/动作/表情/光线/氛围/衣着颜色）尽量保留原文，不要凭空添加新画面内容。
4. 输出 ≤80 字的一段描述，不要 JSON，不要解释，不要 markdown。

旧描述: {old_vs}

修正后: 人物={chars} 地点={loc} 事件={event}

重写:"""


def find_rewrite_targets(ep: int) -> list:
    """找出该集需要重写的场景: [(scene_idx, old_vs, new_scene_dict)]"""
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    pre = sm_file.with_suffix(".json.precalib")
    vlm_file = SOURCES_DIR / f"ep{ep}" / "vlm_seg_cache_v3.json"
    if not sm_file.exists() or not pre.exists() or not vlm_file.exists():
        return []
    old = json.load(open(pre))
    new = json.load(open(sm_file))
    vlm = json.load(open(vlm_file))
    targets = []
    for i, (o, n) in enumerate(zip(old, new)):
        if o.get('characters') == n.get('characters'):
            continue
        removed = set(o.get('characters', [])) - set(n.get('characters', []))
        vs = vlm.get(str(i), {}).get('visual_summary', '')
        if any(r and r in vs for r in removed):
            targets.append((i, vs, n))
    return targets


def rewrite_batch(ep: int, batch: list) -> dict:
    """重写一批 → {scene_idx: new_vs}"""
    lines = []
    for i, vs, n in batch:
        chars = '、'.join(n.get('characters', []))
        lines.append(f"--- 场景{i} ---\n旧描述: {vs}\n修正后: 人物={chars} 地点={n.get('location','')} 事件={n.get('event','')}")
    user = f"第{ep}集 需重写的场景:\n\n" + "\n\n".join(lines)
    res = call_deepseek(REWRITE_PROMPT, user, temperature=0.2, max_tokens=2000,
                        timeout=120, label=f"rewrite_ep{ep}")
    if not res.get("ok"):
        print(f"  ⚠ 批调用失败: {res.get('error','?')[:80]}")
        return {}
    text = (res.get("content") or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # 按 "--- 场景N ---" 切分, 每段重写对应场景
    # 但模型不一定回显场景号, 退回顺序匹配
    parts = re.split(r'---\s*场景\s*(\d+)\s*---', text)
    result = {}
    if len(parts) >= 3:
        # parts[0]=前导, 然后成对 (idx, body)
        for j in range(1, len(parts), 2):
            idx = int(parts[j])
            body = parts[j+1].strip()
            if body:
                result[idx] = body[:200]
    if not result:
        # 顺序匹配
        bodies = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
        for k, (i, vs, n) in enumerate(batch):
            if k < len(bodies) and bodies[k]:
                result[i] = bodies[k][:200]
    return result


def main():
    p = argparse.ArgumentParser(description="VLM visual_summary 对齐重写")
    p.add_argument("--ep", default=None, help="单集/多集 (逗号分隔)")
    p.add_argument("--batch", type=int, default=8, help="每批场景数")
    p.add_argument("--dry-run", action="store_true", help="只看不改")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())

    total_targets = 0
    for ep in eps:
        targets = find_rewrite_targets(ep)
        if not targets:
            continue
        total_targets += len(targets)
        print(f"=== EP{ep}: {len(targets)} 段需重写 ===")
        if args.dry_run:
            for i, vs, n in targets:
                print(f"  S{i}: {vs[:50]}... -> chars={n['characters']}")
            continue

        vlm_file = SOURCES_DIR / f"ep{ep}" / "vlm_seg_cache_v3.json"
        vlm = json.load(open(vlm_file))
        rewritten = 0
        failed_scenes = []
        for bi in range(0, len(targets), args.batch):
            batch = targets[bi:bi + args.batch]
            result = rewrite_batch(ep, batch)
            for i, vs, n in batch:
                new_vs = result.get(i, "").strip()
                if new_vs:
                    vlm[str(i)]["visual_summary"] = new_vs
                    vlm[str(i)]["_chars"] = n.get('characters', [])
                    rewritten += 1
                    print(f"  ✅ S{i}: {vs[:40]}... -> {new_vs[:40]}...")
                else:
                    failed_scenes.append((i, vs, n))
                    print(f"  ⚠ S{i}: 批量未返回, 待单场景重试")
        # 单场景重试 (最可靠, 无解析歧义)
        for i, vs, n in failed_scenes:
            user = (f"--- 场景{i} ---\n旧描述: {vs}\n修正后: "
                    f"人物={'、'.join(n.get('characters', []))} 地点={n.get('location','')} "
                    f"事件={n.get('event','')}")
            res = call_deepseek(REWRITE_PROMPT, user, temperature=0.2, max_tokens=800,
                                timeout=120, label=f"rewrite_ep{ep}_s{i}")
            new_vs = (res.get("content") or "").strip()
            if new_vs:
                vlm[str(i)]["visual_summary"] = new_vs[:200]
                vlm[str(i)]["_chars"] = n.get('characters', [])
                rewritten += 1
                print(f"  ✅(单场景) S{i}: {vs[:40]}... -> {new_vs[:40]}...")
            else:
                print(f"  ❌ S{i}: 单场景重试仍失败")
        if rewritten:
            json.dump(vlm, open(vlm_file, "w"), ensure_ascii=False, indent=2)
            print(f"  已落盘 {rewritten} 段")

    print(f"\n共需重写 {total_targets} 段")


if __name__ == "__main__":
    main()
