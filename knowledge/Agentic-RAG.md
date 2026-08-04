---
title: Agentic-RAG
type: topic
tags: [technique, concept, frontier]
difficulty: 前沿
prerequisites: ["Agent核心概念", "RAG核心概念"]
status: planned
created: 2026-08-04
---

# Agentic RAG

> 当 RAG 遇到 Agent：让 AI 自主决定搜什么、搜几次、怎么筛选

## 是什么

Agentic RAG = Agent + RAG。不是"用户问一句 → 搜一次 → 答一次"，而是 **Agent 自主规划搜索策略、执行多轮检索、评估结果质量、调整方向，直到找到满意的答案。**

## Naive RAG vs Agentic RAG

| | Naive RAG | Agentic RAG |
|---|---|---|
| 检索次数 | 1 次 | Agent 决定 (1-N 次) |
| 查询策略 | 用户给什么搜什么 | Agent 改写、拆分、组合查询 |
| 结果评估 | 按相似度排序 | Agent 评估相关性 + 信息完整性 |
| 搜索模式 | 固定 (向量/混合) | Agent 选择最合适的模式 |
| 是否迭代 | 否 | 是 — "不够好就换方向再搜" |

## 在 VibeCut 中的应用（规划）

ChatPanel 当前是"LLM 精炼 query → 搜索 → 返回结果"。升级为 Agentic RAG 后：

```
用户: "找苏大强在老宅发火的戏"

Agent 内部:
  Round 1: 搜"苏大强 老宅 发火" → 找到 3 个
  Agent: "只有 3 个，而且都是 EP1 的。搜一下 EP38 的回忆片段"
  Round 2: 搜"苏大强 老宅 回忆 EP38" → 找到 2 个
  Agent: "EP38 有一个院子场景质量很高，加上前面 3 个，够了"
  返回: 5 个最佳结果 + 推荐选择
```

## 核心技术

- **Planning:** Agent 先想好搜什么方向
- **Multi-step Retrieval:** 多次搜索，每次结果指导下一次
- **Self-Critique:** Agent 评估结果质量，决定是否继续
- **Tool Selection:** 语义搜索 vs 关键词搜索 vs 混合，Agent 选

## 前置知识

- [[Agent核心概念]] — Agent 的决策循环
- [[RAG核心概念]] — RAG 的基本流程
- [[LangGraph框架]] — 实现 Agentic RAG 的框架

## 延伸

- [[Agent自我学习]] — 从搜索经验中学习更好的策略
- `docs/tech/AGENT_ARCHITECTURE.md` — SearchAgent StateGraph 设计
