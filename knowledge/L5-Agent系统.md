---
title: L5-Agent系统
type: moc
tags: [moc, concept, planned]
created: 2026-08-04
---

# L5: Agent 系统

> VibeCut 从"AI 辅助"到"AI 自主"的质变层 — Agent 编排、工具使用、人机协作

## 本层知识点

| 笔记 | 主题 | 难度 | 状态 |
|------|------|------|------|
| [[Agent核心概念]] | Agent 定义、三要素、Agent Loop | 🔴 | 📝 |
| [[Agent职责分离]] | 生成层 vs 决策层、制片Agent案例 | 🔴 | 📝 |
| [[Agent测试与评估]] | Harness、评估边界、对比评估 | 🔴 | 📝 |
| [[LangGraph框架]] | StateGraph, Node, ConditionalEdge, Checkpointer | 🔴 | 🔄 |
| [[工具定义与MCP]] | Tool Schema, MCP 协议, 工具标准化 | 🔴 | 🔄 |
| [[人机协作HITL]] | interrupt/resume, 审批流设计 | 🔴 | 🔄 |
| [[Agent-First方法论]] | AFDD 开发方法论 | 🔴 | 📝 |
| [[LLM调用与工具使用]] | Function Calling, Tool Use 的底层机制 | 🔴 | 📝 |

## 为什么这层是质变

前面四层（L1-L4）让 VibeCut 成为一个**功能强大的 AI 辅助工具**。

L5 让它变成一个**自主的 AI 剪辑师**。

区别：
- L1-L4: 人类决定做什么，AI 执行
- L5: Agent 决定做什么，人类审核

## Agent 化的三个关键能力

```
1. 自主规划 (Planning)
   从 "输入主题，点生成" → "理解目标，自主设计剪辑方案"

2. 工具使用 (Tool Use)
   从 "一个 BGE 搜索函数" → "10+ 工具，Agent 自主选择调用哪个"

3. 自我反思 (Reflection)
   从 "人类审核脚本" → "Agent 自我审核，不通过自动修复，通过后请人类确认"
```

## 与其他层的关系

```
L4 (RAG体系) ──→ L5 (Agent系统) ──→ L6 (前端工程)
  检索工具         编排引擎             Agent UI
                    │
                    ├── LangGraph StateGraph
                    ├── 12 个 VIBECUT_TOOLS
                    ├── 3 层记忆 (工作/会话/长期)
                    └── Human-in-the-Loop 审批流
                         │
                         ▼
                    L7 (前沿探索)
                      Agentic RAG / 多Agent / 自我学习
```

## 学习路径

```
起点: [[Agent核心概念]] — 理解 Agent 是什么
  ↓
[[LLM调用与工具使用]] — 理解 Tool Use 的底层机制
  ↓
[[LangGraph框架]] — 动手用 LangGraph 写一个简单 Agent
  ↓
[[工具定义与MCP]] — 理解工具接口标准化
  ↓
[[人机协作HITL]] — 设计人机协作边界
  ↓
[[Agent-First方法论]] — 从方法论高度理解 Agent 开发
  ↓
[[Agent测试与评估]] — 用 Harness 评估 Agent 输出质量
```
