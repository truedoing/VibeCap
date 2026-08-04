---
title: Agent核心概念
type: topic
tags: [concept, planned]
difficulty: 进阶
prerequisites: ["大语言模型LLM", "RAG核心概念"]
status: planned
created: 2026-08-04
---

# Agent 核心概念

> Agent = LLM + 工具 + 自主决策循环。从"回答问题"到"自主完成任务的 AI"

## 什么是 Agent

**Agent（智能体）** 是一个能自主使用工具、做出决策、完成多步骤任务的 AI 系统。

```
Chatbot vs Agent:

Chatbot:                               Agent:
"帮我搜苏大强在老宅的画面"              "剪一个60秒关于苏大强家庭矛盾的视频"
  → LLM 直接回答                        → Agent 自主:
  → 可能调一次搜索                       1. 搜索苏大强家庭矛盾的素材 (调搜索工具)
                                        2. 分析哪些片段适合做开场 (调LLM分析)
                                        3. 设计叙事结构 (调策划工具)
                                        4. 选句+压缩脚本 (调写作+编辑工具)
                                        5. 自我审核，不通过则修改
                                        6. 输出完整脚本
```

## 为什么需要 Agent

VibeCut 当前的问题：人类需要点击 10 次按钮才能完成一个视频。每次点击背后都是一个 LLM 调用，但 **LLM 不知道自己在上一步做了什么，也不知道下一步应该做什么**。

Agent 解决的问题：**把编排权从人类交给 LLM。**

## Agent 的三要素

```
        ┌──────────┐
        │  LLM     │ ← 大脑: 推理、规划、决策
        │  (大脑)  │
        └─────┬────┘
              │
    ┌─────────┼─────────┐
    │         │         │
    ▼         ▼         ▼
┌──────┐ ┌──────┐ ┌──────┐
│工具A │ │工具B │ │工具C │ ← 手脚: 搜索/分析/导出...
└──────┘ └──────┘ └──────┘
    │         │         │
    └─────────┼─────────┘
              │
              ▼
        ┌──────────┐
        │  Memory  │ ← 记忆: 短期(当前任务状态)
        │  (记忆)  │         长期(用户偏好、历史经验)
        └──────────┘
```

## Agent Loop（核心循环）

所有 Agent 系统的本质都是一个循环：

```
┌──────────────────────────────────────────────┐
│                                              │
│  ┌──────────┐     ┌──────────┐               │
│  │ Observe  │ ←── │  Think   │               │
│  │ (观察)   │     │  (思考)  │               │
│  └────┬─────┘     └────┬─────┘               │
│       │                │                     │
│       │           ┌────▼─────┐               │
│       │           │  Decide  │               │
│       │           │  (决策)  │               │
│       │           └────┬─────┘               │
│       │                │                     │
│       │     ┌──────────┼──────────┐          │
│       │     │          │          │          │
│       │     ▼          ▼          ▼          │
│       │  调用工具   等待人类   完成任务        │
│       │     │          │          │          │
│       └─────┴──────────┴──────────┘          │
│                                              │
│  循环直到任务完成或人类叫停                      │
└──────────────────────────────────────────────┘
```

## Agent 的能力等级

| Level | 名称 | 能力 | VibeCut 对应 |
|-------|------|------|-------------|
| L1 | Tool Use | LLM 能调用预定义的工具 | 当前 ChatPanel 的搜索 |
| L2 | Planning | LLM 能制定多步计划 | run_pipeline 硬编码的计划 |
| L3 | Reflection | LLM 能评估自己的输出并修正 | reviewer→retry 循环 |
| L4 | Autonomy | LLM 自主决策下一步做什么 | 🔄 规划中的 Orchestrator |
| L5 | Learning | 从历史经验中自我改进 | 📅 远期目标 |

## VibeCut 的 Agent 化路径

当前 VibeCut 的 `script_agents.py` 处于 L2-L3 的混合状态：
- ✅ L1 (Tool Use): ChatPanel 搜索是基础的 Tool Use
- ✅ L2 (Planning): `run_pipeline()` 有固定的计划
- ⚠️ L3 (Reflection): reviewer→retry 是初级的反思循环，但修复策略是硬编码的
- ❌ L4 (Autonomy): Agent 不能自己决定"接下来做什么"

升级到 LangGraph 后，`run_pipeline()` 中的硬编码编排逻辑会被 StateGraph + ConditionalEdge 替代，Agent 达到 L4。

## 前置知识

- [[大语言模型LLM]] — Agent 的"大脑"就是 LLM
- [[LLM调用与工具使用]] — Tool Use 是 Agent 的基础能力
- [[LangGraph框架]] — 当前最成熟的 Agent 构建框架

## 延伸

- [[Agentic-RAG]] — Agent + RAG 的结合
- [[人机协作HITL]] — Agent 不完全自主，关键节点需要人类确认
- [[多Agent协作]] — 多个 Agent 分工合作
- [[Agent自我学习]] — Agent 从经验中改进
- [[工具定义与MCP]] — Agent 的工具标准化

## 学习资源

- Anthropic: "Building Effective Agents" (2024.12) — Agent 设计原则的权威指南
- LangGraph 官方文档 — Agent 开发的实践框架
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut Agent 架构详细设计
