"""检索层 Harness — 只测深层 RAG 检索这一步（_infer_episodes_from_topic_llm）

与 test_rag.py（端到端 harness，~80s）不同：
- 这里只调检索函数，1 次 LLM 调用/案例，~9s
- 金标准 ground truth 从结构化 synopsis 的「真实弧线节点」提取，而非人工凭记忆标注

运行:
  cd vibecut-server && python3 tests/harness_retrieval.py
"""
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.env import load_env
load_env()

from agents.drama_script_agents import _infer_episodes_from_topic_llm

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"

# ── 金标准案例集 ────────────────────────────────────────────────
# ground truth = 从 scene_map / 结构化 synopsis 里可验证的真实弧线节点
# （不是人工凭记忆标注，见 RAG_RETRIEVAL_TEST.md 的教训）
CASES = [
    {
        "name": "苏明成人物线:从妈宝到守护者",
        "topic": "苏明成人物线:从妈宝到守护者",
        # 苏明成真实弧线节点（从 character_arcs 提取）：
        # EP21 打人入狱(冰点) / EP32 离婚(谷底) / EP37 卖房道歉 / EP39 打架关系改善 / EP44-45 和解
        "ground_truth": [21, 32, 37, 39, 45],
    },
    {
        "name": "苏明玉人物线:从冷漠到守护家庭",
        "topic": "苏明玉人物线:从冷漠到守护家庭",
        # EP21 考虑和解 / EP38 宽容为兄调解 / EP39 放下执着与苏明成和解 / EP42 主动让父亲住进自己家
        "ground_truth": [21, 38, 39, 42],
    },
    {
        "name": "苏大强人物线:从作到担责",
        "topic": "苏大强人物线:从作到担责",
        # EP44 立遗嘱展现关爱 / EP45 接受现实托付后事
        "ground_truth": [44, 45],
    },
]


def recall(inferred, ground_truth):
    """召回率 = 命中的 ground truth 节点数 / ground truth 总数"""
    hit = [e for e in ground_truth if e in inferred]
    return len(hit) / len(ground_truth), hit


def run_one(case):
    inferred = _infer_episodes_from_topic_llm(PROJECT_DIR, case["topic"])
    if not inferred:
        return {"name": case["name"], "inferred": None, "recall": 0.0, "hit": []}
    rec, hit = recall(inferred, case["ground_truth"])
    return {
        "name": case["name"],
        "inferred": inferred,
        "ground_truth": case["ground_truth"],
        "recall": round(rec, 2),
        "hit": hit,
    }


def main():
    print("=" * 70)
    print("检索层 Harness：深层 RAG 反推质量评估")
    print("=" * 70)
    results = []
    for case in CASES:
        print(f"\n▶ 案例: {case['name']}")
        print(f"  ground_truth (真实弧线节点): {case['ground_truth']}")
        r = run_one(case)
        results.append(r)
        if r["inferred"] is None:
            print("  ❌ 反推失败（返回 None）")
        else:
            print(f"  反推结果: {r['inferred']}")
            print(f"  召回率: {r['recall']}  命中: {r['hit']}")

    # 汇总
    avg = sum(r["recall"] for r in results) / len(results) if results else 0
    print("\n" + "=" * 70)
    print(f"平均召回率: {avg:.2f}")
    for r in results:
        print(f"  {r['name']}: {r['recall']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
