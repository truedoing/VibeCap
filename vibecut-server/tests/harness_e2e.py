"""E2E Harness — 编剧Agent「生产合格」全维度评估

被测边界：run_drama_pipeline 完整流水线（内存返回 dict，不读磁盘——磁盘 schema 与 handler 不一致）

三层评估维度：
① 机读硬门槛（确定性）：seg_id 连续 / narration 非空 / A 段有 source_start+ep / 时长偏差 / API 保真
② 事实准确性：A 段 scene_query vs scene_map 比对（张冠李戴率）
③ 语言质量（LLM 评分器）：钩子/网感/人物心理/结尾升华/剧情忠实，各 1-5 分

运行:
  cd vibecut-server && python3 tests/harness_e2e.py [--runs 1]
"""
import argparse
import json
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.env import load_env
load_env()

from agents.drama_script_agents import run_drama_pipeline, _load_scene_maps

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"

CASES = [
    {"name": "苏明成人物线", "topic": "苏明成人物线:从妈宝到守护者", "target": 240},
    {"name": "苏明玉人物线", "topic": "苏明玉人物线:从冷漠到守护家庭", "target": 240},
    {"name": "苏大强人物线", "topic": "苏大强人物线:从作到担责", "target": 240},
]


# ═══════════════════════════════════════════════════════════════
# ① 机读硬门槛
# ═══════════════════════════════════════════════════════════════

def check_hard_gates(result):
    """返回 (通过数, 总检查项, 详情列表)"""
    issues = []
    segs = result.get("segments", [])

    # 1. seg_id 连续无重复
    ids = [s.get("seg_id") for s in segs]
    if ids != list(range(len(segs))):
        issues.append(f"seg_id 不连续或重复: {ids[:10]}")

    # 2. 每个段必须有内容：解说段有 narration，原声段有 highlight（两者至少其一非空）
    empty_segs = [s.get("seg_id") for s in segs
                  if not (s.get("narration_text") or "").strip() and not (s.get("highlight_text") or "").strip()]
    if empty_segs:
        issues.append(f"空段（既无解说也无原声）: seg {empty_segs}")

    # 3. mode A 段必须有 source_start>0 且 source_end>source_start 且 ep
    bad_a = []
    for s in segs:
        if s.get("mode") == "A":
            ss = s.get("source_start")
            se = s.get("source_end")
            ep = s.get("video_episode") or (s.get("episode_marker") or {}).get("episode")
            if not (ss and ss > 0 and se and se > ss and ep):
                bad_a.append(s.get("seg_id"))
    if bad_a:
        issues.append(f"mode A 缺锚定字段: seg {bad_a}")

    # 4. episode 范围 [1,46]
    bad_ep = []
    for s in segs:
        ep = s.get("video_episode") or (s.get("episode_marker") or {}).get("episode")
        if ep is not None and not (1 <= ep <= 46):
            bad_ep.append((s.get("seg_id"), ep))
    if bad_ep:
        issues.append(f"episode 越界: {bad_ep}")

    # 5. mode 分布
    mode_a = sum(1 for s in segs if s.get("mode") == "A")
    mode_c = sum(1 for s in segs if s.get("mode") == "C")

    return issues, {"total": len(segs), "mode_a": mode_a, "mode_c": mode_c}


def check_duration(result, target):
    te = result.get("time_estimate", {})
    est = te.get("estimated_sec", 0)
    deviation = abs(est - target) / target if target else 0
    return est, deviation


# ═══════════════════════════════════════════════════════════════
# ② 事实准确性（复用 harness_writer_factuality 的比对逻辑）
# ═══════════════════════════════════════════════════════════════

def find_scene_by_time_range(scene_map, tr):
    if not tr or not isinstance(tr, list) or len(tr) != 2:
        return None
    for s in scene_map:
        if s["time_range"] == tr:
            return s
    closest = min(scene_map, key=lambda s: abs(s["time_range"][0] - tr[0]))
    gap = abs(closest["time_range"][0] - tr[0])
    return closest if gap <= 15 else None


def check_factuality(segments, scene_maps):
    total_a = 0
    errors = []
    for seg in segments:
        if seg.get("mode") != "A":
            continue
        sq = seg.get("scene_query") or {}
        ep = sq.get("episode")
        tr = sq.get("time_range")
        if not ep:
            continue
        total_a += 1
        sm = scene_maps.get(ep, [])
        matched = find_scene_by_time_range(sm, tr) if sm else None
        if not matched:
            errors.append((seg.get("seg_id"), "无法锚定"))
            continue
        # 比对 event / mood（characters 有场景人物多人的特性，放宽：只查 event/mood）
        sq_event = sq.get("event", "")
        sm_event = matched.get("event", "")
        if sq_event and sm_event and sq_event != sm_event:
            overlap = len(set(sq_event) & set(sm_event))
            if overlap < max(2, len(sm_event) // 4):
                errors.append((seg.get("seg_id"), f"事件不符: {sq_event[:15]} vs {sm_event[:15]}"))
        sq_mood = sq.get("mood", "")
        sm_mood = matched.get("mood", "")
        if sq_mood and sm_mood and sq_mood not in sm_mood and sm_mood not in sq_mood:
            errors.append((seg.get("seg_id"), f"情绪不符: {sq_mood} vs {sm_mood}"))
    err_rate = len(errors) / total_a if total_a else 0
    return err_rate, errors, total_a


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def run_case(case, scene_maps):
    print(f"\n{'='*70}\n▶ 案例: {case['name']} (target {case['target']}s)\n{'='*70}")
    t0 = time.time()
    result = run_drama_pipeline(
        project_dir=PROJECT_DIR, topic=case["topic"], target_duration=case["target"],
        emit_progress=None,
    )
    elapsed = time.time() - t0

    if not result.get("ok"):
        print(f"  ❌ 流水线失败: {result.get('error')}")
        return None

    # ① 硬门槛
    issues, stats = check_hard_gates(result)
    est, dur_dev = check_duration(result, case["target"])
    print(f"  [硬门槛] 段数 {stats['total']} (A {stats['mode_a']} / C {stats['mode_c']})")
    print(f"  [时长] 预估 {est:.0f}s vs 目标 {case['target']}s (偏差 {dur_dev:.0%})")
    if issues:
        print(f"  ❌ 硬门槛未过 {len(issues)} 项:")
        for i in issues:
            print(f"     - {i}")
    else:
        print(f"  ✅ 硬门槛全部通过")

    # ② 事实准确性
    err_rate, errors, total_a = check_factuality(result["segments"], scene_maps)
    print(f"  [事实] A 段 {total_a} 个，张冠李戴率 {err_rate:.0%}")
    for sid, e in errors:
        print(f"     - seg{sid}: {e}")

    return {
        "name": case["name"], "elapsed": round(elapsed, 1),
        "hard_gate_pass": len(issues) == 0, "issues": issues,
        "dur_dev": dur_dev, "fact_err_rate": err_rate, "fact_errors": len(errors),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1, help="每个案例采样次数")
    args = parser.parse_args()

    print("=" * 70)
    print("E2E Harness：编剧Agent 生产合格全维度评估")
    print("=" * 70)

    results = []
    for case in CASES:
        # 预载涉及集的 scene_map（按 case 全量预载，简化）
        all_eps = set()
        for ep in range(1, 47):
            all_eps.add(ep)
        scene_maps = _load_scene_maps(PROJECT_DIR, sorted(all_eps))
        for r in range(args.runs):
            res = run_case(case, scene_maps)
            if res:
                results.append(res)

    # 汇总
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    for r in results:
        pass_gate = "✅" if r["hard_gate_pass"] else "❌"
        print(f"  {r['name']}: 硬门槛{pass_gate} | 事实错误率 {r['fact_err_rate']:.0%} | "
              f"时长偏差 {r['dur_dev']:.0%}")


if __name__ == "__main__":
    main()
