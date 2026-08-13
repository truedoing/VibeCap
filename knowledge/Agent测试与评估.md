---
title: Agent测试与评估
type: topic
tags: [concept, implemented]
difficulty: 进阶
prerequisites: ["Agent核心概念", "大语言模型LLM"]
status: implemented
created: 2026-08-13
---

# Agent 测试与评估

> Agent 应用里，LLM 输出的不确定性让传统断言式测试失效。测试被分成两层：确定性部分用 `assert`，概率性部分用 **Harness** 评分。

## 什么是 Harness

**Harness（测试/评估 harness）= 把被测对象「套住」、反复喂输入、收集输出、按固定标准评分的那一层脚手架。**

- 原意「马具/挽具」：套在马身上驾驭它的那套东西。
- 软件里借指：套在被测代码外面的、驱动它和评判它的框架。

```
Harness 五部件：
┌─────────────────────────────────────┐
│ ① 被测对象适配  封装被测函数调用      │
│ ② 固定输入      金标准案例 + ground truth │
│ ③ 输出采集      抓结构化输出字段      │
│ ④ 评分器        把模糊质量变成可比分数 │
│ ⑤ 模式开关      跑不同策略/版本做对比  │
└─────────────────────────────────────┘
```

## 为什么传统测试不够用

传统软件测试断言的是「确定性正确」（输入→输出唯一），而 LLM 输出是「概率性质量」。这是本质区别：

| | 传统软件测试 | Agent/LLM 测试 |
|---|---|---|
| 正确性 | 确定性 | 概率性 |
| 断言方式 | `assert 输出 == 期望` | 「质量分数 ≥ 阈值」 |
| 失败信号 | 崩溃/报错/返回值错 | 「质量不达标」（但没崩） |
| 适用 | 纯函数、API、UI 流程 | 生成内容、检索质量、Agent 决策 |

**结论**：不是"传统测试失效了"，是"Agent 应用里代码天然分两类，测试也分两层"。

```
        ▲
       / \         E2E + 评估：跑完整 pipeline，对比评估质量
      /   \
     / 评估 \      ← 新增层：LLM 输出的对比评估（传统测试没有这一层）
    /-------\
   / 集成测试 \    ← 断言 pipeline 编排正确
  /-----------\
 /  单元测试   \   ← 断言纯函数/确定性逻辑
/---------------\
```

## Harness vs Agent

| | Agent | Harness |
|---|---|---|
| 智能 | 有，能自主决策 | 无，确定性代码 |
| 干什么 | 生成解说词、反推剧集 | 喂输入、抓输出、打分 |
| 可预测 | 不可（概率输出） | 可（普通代码） |
| 角色 | 被测对象（考生） | 测试工具（考场+试卷+评分标准） |

**一句话**：Agent 本身不靠谱（概率性），所以需要一套确定性的、可靠的、可重复的 harness 来「套住」它、量它。

## 关键原则：Harness 对应「被测边界」

不是"一个 harness 锁死一个 Agent"，而是"你想测哪一层，harness 就套在哪一层"。

| Harness | 套哪个边界 | 成本 |
|---|---|---|
| A · 检索 | `_infer_episodes_from_topic_llm` | 1 次 LLM |
| B · 故事师 | `story_master_agent` | 1 次 LLM |
| C · 端到端 | `run_drama_pipeline` | 4+ 次 LLM |

**教训**：边界和评估点必须对齐。用一个 80 秒的流水线 harness（C）去测一个 9 秒的检索步骤（A），后面三步全是"陪跑"。

## 确定性 vs 概率性的切分

代码天然分两类，测试策略不同：

- **确定性部分**（纯函数、数据加载、字段校验）→ pytest 单测，`assert`，0 LLM 成本。
- **概率性部分**（LLM 生成、检索质量、Agent 决策）→ harness 评估，`质量分数`。

## 评估指标的 ground truth 问题

LLM 测试最难的是"拿什么当标准答案"。两个陷阱：

1. **人工标注有偏差**：人凭记忆标注的关键集，可能和真实数据不一致（如苏明成弧线的真实终点是 EP37/45，不是人工以为的 EP41）。
2. **ground truth 要可验证**：应从"结构化数据里可验证的事实"（scene_map / 结构化 synopsis 的弧线节点）出发，而非"人工凭记忆标注"。

## 在 VibeCut 中的应用

- 完整设计见 `docs/tech/AGENT_TESTING.md`
- 检索键选型的实证对比（for 循环 / BGE / LLM 语义，V1→V5）见 `docs/tech/RAG_RETRIEVAL_TEST.md`
- 三层已落地：`tests/test_drama_deterministic.py`（确定性单测）、`tests/harness_retrieval.py`（检索）、`tests/harness_writer_factuality.py`（文案师事实准确性）

### 实战成果：度量驱动优化闭环（2026-08-13）

文案师事实准确性 harness 走通了完整闭环，错误率 **6.69% → 1.57%（降幅 76.5%）**：

| 阶段 | 动作 | 平均错误率 |
|---|---|---|
| ① 基线 | 5 次采样测基线 | 6.69% |
| ② 改 prompt | 加"scene_query 字段原样复制"铁律 | 3.75%（事件/人物归零） |
| ③ 治本数据 | 规范化 scene_map 13 个词表外 mood | **1.57%** |

**关键洞察**：情绪维度降不下来时，诊断发现根因在 **ground truth 本身**（scene_map 有 13 个词表外标签），而非 LLM。这印证了「校验的上限取决于 ground truth 质量」。多次采样是必须的——单次错误率波动 0%～17.86%，只看一次会误判。

## 前置知识

- [[Agent核心概念]] — 先理解 Agent 是什么、为什么不可预测
- [[大语言模型LLM]] — LLM 概率输出是"测试分两层"的根源

## 延伸

- [[Agent核心概念]] — Agent 三要素、Agent Loop
- [[Agent-First方法论]] — 从开发方法论高度看 Agent（测试是其收尾一环）
- [[人机协作HITL]] — 人工审核也是"评估"的一种形态

## 学习资源

- Anthropic: "Building Effective Agents" — 含 Agent 评估原则
- LangSmith (LangChain 官方评测平台) — 业界 harness 的成熟形态
- `docs/tech/AGENT_TESTING.md` — VibeCut 的测试框架设计
