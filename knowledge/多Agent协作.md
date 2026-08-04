---
title: 多Agent协作
type: topic
tags: [concept, frontier]
difficulty: 前沿
prerequisites: ["Agent核心概念", "LangGraph框架"]
status: frontier
created: 2026-08-04
---

# 多 Agent 协作

> 从单 Agent 到 Agent 团队 — 不同专长的 Agent 分工协作

## 是什么

多 Agent 系统由多个具有不同专长的 Agent 组成，每个 Agent 有自己的"人设"和工具，Agent 之间可以通信、协商、互相审核。

## 为什么需要

单个 Agent 同时擅长"快节奏剪法"和"情感向剪法"是很难的——这两种风格要求不同的素材选择策略、不同的叙事节奏、不同的审核标准。

多 Agent 方案：不同剪辑风格对应不同的 Agent。用户选风格 = 选择对应的 Agent 团队。

## 在 VibeCut 中的愿景

```
用户: "剪一个关于苏大强的情感向视频"

Coordinator Agent:
  ├── "情感向场景" → 分派给 EmotionAgent
  │     EmotionAgent 擅长: 慢节奏、共情层、长镜头
  ├── "冲突场景" → 分派给 ConflictAgent
  │     ConflictAgent 擅长: 快切、激将法、对话交锋
  └── 最终合成: EditorAgent 合并两边的素材
```

## 两种协作模式

| 模式 | 架构 | 适合 |
|------|------|------|
| **Sequential** | Agent A → Agent B → Agent C | 流水线型任务 |
| **Hierarchical** | Manager Agent 分派给 Specialist Agents | 复杂任务分解 |
| **Debate** | 多个 Agent 独立产方案 → 投票/比较 | 创意型决策 |

## 前置知识

- [[Agent核心概念]] — 单 Agent 是基础
- [[LangGraph框架]] — 多 Agent 的编排层
- [[Agent-First方法论]] — Agent Persona 设计

## 学习资源

- Microsoft AutoGen — 多 Agent 对话框架
- CrewAI — 角色扮演型多 Agent
- LangGraph Multi-Agent examples
