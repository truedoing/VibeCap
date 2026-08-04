---
title: Agentic-RAG
type: topic
tags: [technique, concept, frontier]
difficulty: 前沿
prerequisites: ["RAG核心概念", "Agent核心概念", "LangGraph框架"]
status: planned
created: 2026-08-04
---

# Agentic RAG

> 当 RAG 的"检索"不是固定算法，而是 Agent 的自主决策时，你就得到了 Agentic RAG。

## 是什么

Naive RAG：搜索一次，找到 Top-K，喂给 LLM，生成答案。整个流程是固定的、线性的。

Agentic RAG：**Agent 自己决定搜什么、搜几次、怎么筛选、要不要换个策略再搜。**

```
Naive RAG:                          Agentic RAG:

用户: "苏大强的家庭悲剧"              用户: "剪一个苏大强家庭悲剧的解说"
  │                                    │
  ▼                                    ▼
encode("苏大强的家庭悲剧")             Agent: "这个任务需要展现苏大强
  │                                       如何被家庭矛盾逐步压垮。
  ▼                                       我先拆成几个子主题——"
cosine_sim(所有文档)                        │
  │                                    ┌────┼────┐
  ▼                                    ▼    ▼    ▼
Top-K 结果 → Prompt → LLM 回答       冲突   要钱   独处
                                      │     │     │
                                      ▼     ▼     ▼
                                   各搜 3-5 条，评估质量
                                      │
                                      ▼
                                   Agent: "冲突 3 条 + 独处 2 条
                                           够了，要钱那条疑似台词
                                           不准确，删掉。"
                                      │
                                      ▼
                                   选 5 条最佳 → 生成脚本
```

区别的核心：**谁决定"接下来搜什么"**。Naive RAG 是代码决定的（一次性编码 + 一次性搜索）。Agentic RAG 是 Agent 决定的（多轮搜索 + 评估 + 调整策略）。

## 为什么需要 Agentic RAG

VibeCut 的当前搜索（`_hybrid_search`）有三个局限，Agentic RAG 正好解决：

| 当前局限 | Agentic RAG 如何解决 |
|---------|---------------------|
| 搜索一次，结果取 or 舍 | Agent 多轮搜索，逐轮精化 |
| 不知道"搜够了没" | Agent 评估结果质量，不够就换策略 |
| 无法理解"叙事连贯性" | Agent 搜 A → 发现 B 也相关 → 搜 B → 两个结果搭配使用 |
| 对抽象主题（"家庭悲剧"）只会字面搜索 | Agent 拆解为"冲突""冷战""子女""经济"等子主题，每个找最佳镜头 |

## Naive RAG vs Advanced RAG vs Agentic RAG

| | Naive RAG | Advanced RAG | Agentic RAG |
|---|---|---|---|
| 检索次数 | 1 次 | 1-2 次 | Agent 决定 (1-N 次) |
| 查询策略 | 用户给什么搜什么 | Query 改写 | Agent 拆分、组合、调整 |
| 结果评估 | 按相似度排序 | + 重排 (reranker) | Agent 评估相关性 + 信息完整性 |
| 搜索模式 | 固定 (向量 or 混合) | 多模式融合 | Agent 选择最合适的模式 |
| 是否迭代 | 否 | 否 | 是 — "不够好就换方向再搜" |
| 决策权 | 代码 | 代码 | Agent |

## 关键概念

### 1. SearchAgent 的 StateGraph

VibeCut 规划中的 SearchAgent 架构：

```python
from langgraph.graph import StateGraph
from typing import TypedDict, List

class SearchState(TypedDict):
    user_query: str           # "苏大强家庭悲剧"
    sub_queries: List[str]   # ["苏大强 冲突", "苏大强 子女", ...]
    search_results: dict     # {sub_query: [results]}
    selected_clips: List     # 最终选中的镜头
    iteration: int           # 搜索轮次（上限 3）
    done: bool

workflow = StateGraph(SearchState)

# Node 1: 分析查询 → LLM 拆分成子查询
def analyze_query(state):
    sub_queries = llm.decompose(state["user_query"])
    # "家庭悲剧" → ["冲突", "子女", "独处", "经济"]
    return {"sub_queries": sub_queries}

# Node 2: 对每个子查询执行 BGE 搜索
def search(state):
    results = {}
    for q in state["sub_queries"]:
        results[q] = bge_search(q, limit=5)
    return {"search_results": results}

# Node 3: 评估覆盖度 → 决定是否继续
def evaluate(state):
    if enough_coverage(state["search_results"]):
        return {"done": True}
    elif state["iteration"] >= 3:
        return {"done": True}  # 上限，不无限搜
    else:
        # LLM 建议新搜索方向
        new_subs = llm.suggest_new_angles(state)
        return {"sub_queries": state["sub_queries"] + new_subs,
                "iteration": state["iteration"] + 1}

# Node 4: LLM 从候选镜头中挑选最佳组合
def select(state):
    clips = llm.select_best_clips(
        state["search_results"],
        criteria=["多样性", "叙事连贯", "时长匹配"]
    )
    return {"selected_clips": clips, "done": True}

# 条件路由
workflow.add_conditional_edges("evaluate",
    lambda s: "select" if s["done"] else "search")
```

### 2. 与当前 ChatPanel 的关系

当前 `ChatPanel.jsx` 的多轮对话是**手动版的** Agentic RAG：

```
用户: "搜苏大强发怒的镜头"
ChatPanel → /search → 10 条结果

用户: "不要 EP3 的，找后面的"
ChatPanel → /search → 手动过滤

用户: "换方向，搜苏大强哭的"
ChatPanel → /search → 新搜索
```

升级后的 SearchAgent 把这个过程自动化：Agent 自己判断是否需要"换方向"，自己决定怎么过滤和组合。人类只在最终选择时介入。

### 3. Agentic RAG 不等于 Agent + RAG

```
Agent + RAG:                       Agentic RAG:
Agent 把 RAG 当作一个"工具"调用   Agent 把检索作为决策循环的一部分
→ Tool Use 级别的集成              → 策略级别的集成

比喻：
超市自助结账（用户扫描商品）       专业采购员（主动判断"这个菜不新鲜，
                                      换个摊位""这样搭更便宜"）
```

## 在 VibeCut 中的应用（规划）

**当前状态（v0.12）：**
- `ChatPanel.jsx` 提供多轮手动对话
- `server.py` 的 `_deep_search()` 是初级的"多轮搜索 + LLM 重排"
- `_expand_query()` 是初级的"子查询生成"

**规划升级（v2.0）：**
- LangGraph SearchAgent 替代 ChatPanel 的单轮搜索模式
- Agent 自主评估搜索结果质量，决定是否需要额外搜索
- Agent 从搜索结果中理解内容，而非仅返回列表
- 人类可以随时介入，修正 Agent 的搜索策略

**为什么这对视频剪辑特别重要：**

视频剪辑搜索天然是多轮、多角度的。比如"搜苏大强家庭矛盾"是一个主题，但它包含多个子场景（争吵、冷战、爆发、后果）。用户通常不知道所有子场景，需要 Agent 帮他们发现"你还可以看看这个角度"。Agent 还需要在"搜得太多"（不精确）和"搜得太少"（覆盖面不够）之间找到平衡。

## 前置知识

- [[RAG核心概念]] — 从 Naive RAG 到 Advanced RAG 的演进
- [[Agent核心概念]] — Agent 的自主决策循环
- [[LangGraph框架]] — StateGraph 构建 Agent 流程的基础设施
- [[混合搜索策略]] — Agentic RAG 中 Agent 可以自主选择不同搜索策略

## 延伸

- [[Agent-First方法论]] — Agentic RAG 是 AFDD 在 RAG 领域的应用
- [[人机协作HITL]] — Agentic RAG 中人类可以修正 Agent 的搜索策略

## 学习资源

- LangGraph 官方 Tutorial: Agentic RAG — 基础 SearchAgent 的 StateGraph 实现
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 的 SearchAgent 详细设计
- `docs/tech/RAG_KNOWLEDGE.md` — RAG 进化路线详解
