---
title: Agentic-RAG
type: topic
tags: [technique, concept, frontier]
difficulty: 前沿
prerequisites: ["RAG核心概念", "Agent核心概念", "混合搜索策略"]
status: frontier
created: 2026-08-04
---

# Agentic RAG

> Agentic RAG = Agent + RAG：不是"一次检索→喂给 LLM"，而是"Agent 自主决定怎么搜、搜几次、搜完要不要修正 query 再来一次"。

## 是什么

**Agentic RAG** 是 RAG 和 Agent 的结合：用一个 Agent 来控制整个检索-生成流程，而非固定的一次性管线。

```
Naive RAG:                          Agentic RAG:
用户问 → 检索一次 → LLM 回答       用户问 → Agent 分析问题
                                          → 制定搜索策略
                                          → 执行搜索（可能多次）
                                          → 评估结果质量
                                          → 不够好 → 改写 query 再搜
                                          → 够了 → 综合多轮结果 → 回答
```

传统的 RAG 把检索当作一个"黑盒步骤"—query 进去，文档出来，LLM 看着文档回答。Agentic RAG 把检索变成 Agent 的一个**工具**——Agent 可以决定什么时候搜、搜什么、搜多少次、搜完要不要换策略。

## 为什么需要 Agentic RAG

VibeCut 当前的搜索流程暴露了 Naive RAG 的问题：

1. **一次搜索不够**：用户搜"苏大强家庭矛盾"，命中的是分散的片段。Agent 需要先搜"苏大强"，再针对热点片段搜"矛盾"、"吵架"等关联词，才能拼出完整的叙事弧线。

2. **固定策略不灵活**：当前 `run_pipeline()` 用的是硬编码策略——搜索一次 → 压缩 → 审核。但当搜索结果质量差时（很多低分片段），Agent 应该自动改写 query 再试。

3. **Agent 应该有检索的自主权**：一个真正的策划 Agent 不会满足于"用户说了什么就搜什么"。它会主动搜相关概念、验证素材是否足够、发现遗漏的角度。

## 关键概念

### 1. 从"查询精炼"到"搜索 Agent"

VibeCut ChatPanel 的升级路径：

```
当前（v0.12）:
  前端发 query → POST /search（`handlers/search.py` BGE 搜索）→ 返回结果
  问题: 一次性，无反馈循环

升级后（Agentic RAG）:
  ChatPanel 发 "策划一个关于 X 的视频"
    → SearchAgent 启动
    → plan_search: "需要搜 X 的核心内容 + 情感高光 + 冲突场景"
    → execute: 并行搜索 3 个 query
    → evaluate: "第一个 query 命中 15 条高质量，后两个不足"
    → decide: "用第一条的结果继续，改写第二条 query"
    → synthesize: 综合所有结果，生成策划方案
```

### 2. SearchAgent StateGraph

用 LangGraph 构建的搜索 Agent 状态图：

```
                    ┌─────────────┐
                    │ plan_search │ ← 分析需求，生成搜索计划
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
              ┌────→│  execute    │ ← 执行一条或多条搜索
              │     └──────┬──────┘
              │            │
              │            ▼
              │     ┌─────────────┐
              │     │  evaluate   │ ← 评估结果质量（相关性、覆盖度）
              │     └──────┬──────┘
              │            │
              │     ┌──────▼──────┐
              │     │   decide    │ ← 决定: continue / rewrite / stop / ask_user
              │     └──────┬──────┘
              │            │
              │  continue  │  stop
              └────────────┘   │
                               ▼
                        ┌─────────────┐
                        │ synthesize  │ ← 综合所有结果，生成回答
                        └─────────────┘
```

`decide` 节点的判断逻辑：
- 所有 query 都有高质量命中 → stop，进入 synthesize
- 部分 query 命中不足 → rewrite 低分 query，回到 execute
- 连续 3 轮改写仍然不够 → ask_user（请求人类补充搜索词）
- 完全没有命中 → ask_user（告知用户，请求换个方向）

### 3. 反馈循环（Feedback Loop）

Agentic RAG 的核心创新是**检索结果的自我评估**：

```python
def evaluate_node(state):
    results = state["search_results"]
    evaluation = {
        "coverage": 0.0,     # 覆盖了用户需求的多少
        "quality": 0.0,      # 结果的平均相关性
        "diversity": 0.0,    # 结果的多样性
        "gaps": [],          # 缺失的角度
    }
    # ... 评估逻辑
    return {"evaluation": evaluation}
```

Agent 不只"搜"，还会"判断搜得好不好"——这是 Agentic RAG 和 Naive RAG 的本质区别。

## 在 VibeCut 中的应用（规划）

当前搜索流程（`handlers/search.py` 的 `search()`）：

```
用户输入 → POST /search → BGE 语义搜索 → 渲染结果
```

规划升级后的 Agentic 搜索流程：

```
用户输入 "策划一个关于 X 的视频"
  → SearchAgent 启动
  → plan_search: LLM 分析需求，生成 3-5 个搜索角度
  → execute: 每个角度 → BGE 语义搜索 → 收集结果
  → evaluate: LLM 评估每个角度的覆盖度
  → decide: 不够的角度改写 query 再来
  → synthesize: LLM 综合所有命中片段，生成脚本大纲
  → 前端 ChatPanel 展示搜索过程和结果
```

## 前置知识

- [[RAG核心概念]] — Naive RAG 的基本流程
- [[Agent核心概念]] — Agent Loop 是 Agentic RAG 的决策基础
- [[混合搜索策略]] — 多 query 搜索的底层实现
- [[向量检索与索引]] — 每次搜索的底层索引查询

## 延伸

- [[Agent-First方法论]] — Agentic RAG 是 Agent-First 在检索场景的应用
- [[人机协作HITL]] — evaluate 阶段的 ask_user 就是一种 HITL
- [[多Agent协作]] — 多个搜索 Agent 并行搜索不同角度

## 动手实验

用自己的话描述一次"搜索失败→改写→成功"的案例：

```
原始 query: "学习方法"
  → 第 1 次搜索: BGE 返回 20 条，前 5 条分数 < 0.3（太泛）
  → Agent 分析: "学习方法"覆盖面太广，需要具体化
  → 改写 query: "高效学习方法 时间管理 记忆技巧"
  → 第 2 次搜索: BGE 返回 20 条，前 8 条分数 > 0.7（优秀！）
  → Agent 决定: 停止搜索，用这 8 条高质量结果生成回答
```

## 学习资源

- LangGraph 官方教程: Agentic RAG — 完整的 SearchAgent 示例
- Anthropic: "Building Effective Agents" (2024.12) — Agent+RAG 设计原则
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut Agentic RAG 详细设计
