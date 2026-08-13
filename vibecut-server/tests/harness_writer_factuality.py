"""文案师事实准确性 Harness — 度量「张冠李戴率」

核心：文案师产出 segments 后，拿每个 segment 的原始 scene_query 去比对该集 scene_map：
- episode 是否有效
- time_range 是否落在该集 scene_map 的某个场景内（对齐）
- 对齐后，scene_query 的 characters / event / mood 与 scene_map 事实是否一致

注意：必须用「文案师原始输出」（script_writer_agent 返回），不能用 Phase 4 覆盖后的结果
——否则覆盖会把错误抹掉，度量就失效了（这正是 AGENT_TESTING.md 里指出的问题）。

运行:
  cd vibecut-server && python3 tests/harness_writer_factuality.py
"""
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.env import load_env
load_env()

from agents.drama_script_agents import script_writer_agent, _load_scene_maps

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"

# 测试章节：复用真实策划师产出的章节结构（从 文案脚本.json 提取的 chapter 形状）
TEST_CHAPTERS = [
    {
        "index": 0,
        "title": "妈宝的底色",
        "narrative_function": "hook",
        "narrative_goal": "建立苏明成妈宝人设",
        "episodes_focus": [1, 9],
        "director_technique": "CONTRAST",
    },
    {
        "index": 1,
        "title": "暴力与坠落",
        "narrative_function": "action",
        "narrative_goal": "苏明成打人入狱、离婚坠落",
        "episodes_focus": [21, 32],
        "director_technique": "REACTION",
    },
    {
        "index": 2,
        "title": "觉醒与守护",
        "narrative_function": "emotion",
        "narrative_goal": "苏明成觉醒、为家人出头",
        "episodes_focus": [37, 39],
        "director_technique": "ARC",
    },
]


def load_scene_map(ep):
    sm = _load_scene_maps(PROJECT_DIR, [ep])
    return sm.get(ep, [])


def find_scene_by_time_range(scene_map, tr):
    """按 time_range 精确对齐，找不到则找最近（gap ≤ 15s）"""
    if not tr or not isinstance(tr, list) or len(tr) != 2:
        return None
    for s in scene_map:
        if s["time_range"] == tr:
            return s
    # 最近匹配
    closest = min(scene_map, key=lambda s: abs(s["time_range"][0] - tr[0]))
    gap = abs(closest["time_range"][0] - tr[0])
    return closest if gap <= 15 else None


def check_segment(seg, scene_maps):
    """检查单个 segment 的事实准确性，返回 (是否张冠李戴, 详情)"""
    sq = seg.get("scene_query") or {}
    ep = sq.get("episode")
    tr = sq.get("time_range")

    # 无 episode → mode C，不算张冠李戴（文案师主动放弃锚定）
    if not ep:
        return {"ok": True, "mode": "C", "reason": "无 episode"}

    sm = scene_maps.get(ep, [])
    if not sm:
        return {"ok": False, "reason": f"EP{ep} 无 scene_map", "mode": "invalid_ep"}

    matched = find_scene_by_time_range(sm, tr)
    if not matched:
        return {"ok": False, "reason": f"EP{ep} time_range {tr} 无法对齐", "mode": "no_anchor"}

    # 对齐了，比对 characters / event / mood
    issues = []
    # 人物：scene_query 的人物是否在 scene_map 场景的 characters 里（至少一个核心人物在场）
    sq_chars = set(sq.get("characters") or [])
    sm_chars = set(matched.get("characters") or [])
    if sq_chars and not (sq_chars & sm_chars):
        issues.append(f"人物全部不在场: 写{sorted(sq_chars)} vs 实{sorted(sm_chars)}")

    # 事件：scene_query 的 event 是否与 scene_map 的 event 一致（字面 or 高重叠）
    sq_event = sq.get("event", "")
    sm_event = matched.get("event", "")
    if sq_event and sm_event and sq_event != sm_event:
        # 简单重叠度：共享 2+ 字词视为一致
        overlap = len(set(sq_event) & set(sm_event))
        if overlap < max(2, len(sm_event) // 4):
            issues.append(f"事件不符: 写'{sq_event[:20]}' vs 实'{sm_event[:20]}'")

    # 情绪：scene_query 的 mood 是否与 scene_map 一致（字面包含）
    sq_mood = sq.get("mood", "")
    sm_mood = matched.get("mood", "")
    if sq_mood and sm_mood and sq_mood not in sm_mood and sm_mood not in sq_mood:
        issues.append(f"情绪不符: 写'{sq_mood}' vs 实'{sm_mood}'")

    if issues:
        return {"ok": False, "reason": "; ".join(issues), "mode": "fact_error"}
    return {"ok": True, "mode": "A", "reason": ""}


def main(runs=3):
    print("=" * 70)
    print(f"文案师事实准确性 Harness：度量「张冠李戴率」（采样 {runs} 次）")
    print("=" * 70)

    # 预加载所有涉及集的 scene_map
    all_eps = set()
    for ch in TEST_CHAPTERS:
        all_eps.update(ch.get("episodes_focus", []))
    scene_maps = _load_scene_maps(PROJECT_DIR, sorted(all_eps))

    # 多次采样累计
    run_err_rates = []
    dim_count = {"mood": 0, "event": 0, "characters": 0, "other": 0}
    grand_total = 0
    grand_err = 0

    for r in range(runs):
        total_ok = 0
        total_err = 0
        total_segments = 0
        print(f"\n── 第 {r+1}/{runs} 次采样 ──")

        for ch in TEST_CHAPTERS:
            result = script_writer_agent(ch, scene_maps)
            if not result.get("ok"):
                print(f"  ❌ 章节「{ch['title']}」调用失败: {result.get('error')[:60]}")
                continue

            segments = result["result"].get("segments", [])
            for i, seg in enumerate(segments):
                total_segments += 1
                check = check_segment(seg, scene_maps)
                if check["ok"]:
                    total_ok += 1
                else:
                    total_err += 1
                    # 按维度归类错误
                    reason = check["reason"]
                    if "情绪" in reason:
                        dim_count["mood"] += 1
                    elif "事件" in reason:
                        dim_count["event"] += 1
                    elif "人物" in reason:
                        dim_count["characters"] += 1
                    else:
                        dim_count["other"] += 1
                    print(f"    ❌ 章节「{ch['title']}」段{i}: {reason}")

        if total_segments:
            rate = total_err / total_segments
            run_err_rates.append(rate)
            grand_total += total_segments
            grand_err += total_err
            print(f"  第 {r+1} 次: {total_ok}/{total_segments} 一致, 错误率 {rate:.2%}")

    # 汇总
    print("\n" + "=" * 70)
    if run_err_rates:
        avg = sum(run_err_rates) / len(run_err_rates)
        print(f"采样次数: {len(run_err_rates)}")
        print(f"平均错误率: {avg:.2%}")
        print(f"单次错误率分布: {[f'{r:.2%}' for r in run_err_rates]}")
        if grand_err:
            print(f"错误维度分布: " +
                  f"情绪 {dim_count['mood']}, 事件 {dim_count['event']}, " +
                  f"人物 {dim_count['characters']}, 其他 {dim_count['other']}")
    else:
        print("无有效采样")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="采样次数")
    args = parser.parse_args()
    main(runs=args.runs)

