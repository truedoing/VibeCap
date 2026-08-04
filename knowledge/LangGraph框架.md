---
title: LangGraph框架
type: topic
tags: [framework, planned]
difficulty: 进阶
prerequisites: ["大语言模型LLM", "Agent核心概念"]
status: planned
created: 2026-08-04
---

# LangGraph 框架

> LangGraph 是 LangChain 公司推出的 Agent 编排框架。核心思想：**Agent 的执行流程是一个有向图，每个步骤是一个节点，条件路由决定下一步去哪。**

## 是什么

LangGraph 把 Agent 的执行流程建模为一个 **StateGraph（状态图）**：

- **State（状态）：** Agent 在任何时刻的完整上下文（当前任务、已搜索的素材、已生成的脚本...）
- **Node（节点）：** Agent 的一个执行步骤（策划、搜索、审核...）
- **Edge（边）：** 步骤间的流转（策划→搜索、审核→修复...）
- **ConditionalEdge（条件边）：** 根据状态决定下一步（审核通过→下一步、不通过→修复）

## 为什么需要

当前 VibeCut 的问题：`run_pipeline()` 里的编排逻辑是硬编码的 if/elif 链。

```
当前: run_pipeline() 手动编排           LangGraph: StateGraph 声明式编排

planning_agent()                        ┌──────────┐
  ↓                                     │ planning │
writer_agent() × N                      └────┬─────┘
  ↓                                          │
editor_agent()                          ┌────▼─────┐
  ↓                                     │  writer  │
reviewer_agent()                        └────┬─────┘
  ↓                                          │
if not passed: goto editor              ┌────▼─────┐
  ↓                                     │  editor  │
return segments                         └────┬─────┘
                                             │
每个步骤人类写的代码决定                ┌────▼─────┐
流程不可见、不可恢复                    │ reviewer │
                                       └────┬─────┘
                                            │
                                       ┌────▼─────┐
                                       │ pass?    │── yes → END
                                       │ no → editor (循环)
                                       └──────────┘

                                       流程是数据，可以可视化
                                       每一步的状态自动保存
                                       中断后可恢复
```

## 关键概念

### 1. StateGraph

```python
from langgraph.graph import StateGraph
from typing import TypedDict

class MyState(TypedDict):
    query: str
    results: list
    approved: bool

workflow = StateGraph(MyState)
```

State 是整个 Agent 的"工作记忆"。每个 Node 读取 State，返回要更新的字段。

### 2. Node（节点）

一个 Node 就是一个函数，接收 State，返回部分更新的 State：

```python
def search_node(state: MyState) -> dict:
    results = do_search(state["query"])
    return {"results": results}  # 只更新 results 字段
```

### 3. Edge vs ConditionalEdge

```
Edge (固定流向):           ConditionalEdge (条件分流):
A ──────────→ B           A ──→ 条件判断 ──→ B (条件满足)
                                        └─→ C (条件不满足)
```

这是 Agent 的"决策点"——审核通过去导出，不通过回修复。

### 4. Checkpointer（检查点）

把 State 的每一步变化持久化到数据库。这意味着：
- Agent 执行到一半，服务器重启 → 从上次断点继续
- 用户关闭浏览器 → 明天打开，Agent 还在上次的地方
- 调试时可以"回放"任意一步的状态

### 5. ToolNode

LangGraph 内置的节点类型，专门处理工具调用。Agent 说"我要调搜索工具"→ ToolNode 自动执行→ 把结果返回给 Agent。

## 在 VibeCut 中的应用（规划）

```
VibeCut Orchestrator = StateGraph(AgentState)

  understand_task → plan_narrative → search_materials
                                       ↓
                                  compose_script
                                       ↓
                                  review_quality
                                    ↙      ↘
                              pass           fail
                                ↓              ↓
                          human_review    auto_fix ──→ review_quality (循环)
                           ↙      ↘
                      approve    revise
                         ↓          ↓
                   refine_clips  plan_narrative (重新设计)
                         ↓
                   build_timeline → export
```

## 前置知识

- [[Agent核心概念]] — LangGraph 就是实现 Agent 的框架
- [[大语言模型LLM]] — Node 内部调用 LLM
- [[工具定义与MCP]] — LangGraph 的 ToolNode 消费工具定义

## 学习资源

- LangGraph 官方 Quick Start — 从零写一个 Agent
- LangGraph 官方 Tutorial: Customer Support Agent — 多节点 + 条件路由 + HITL
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 的 LangGraph 架构设计
