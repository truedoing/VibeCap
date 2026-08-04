---
title: 多Agent协作
type: topic
tags: [concept, frontier]
difficulty: 前沿
prerequisites: ["Agent核心概念", "Agent-First方法论"]
status: frontier
created: 2026-08-04
---

# 多 Agent 协作

> 当单个 Agent 不够用时——不同风格的剪辑工作交给不同的 Agent，它们可以辩论、分工、互相审核。

## 是什么

**多 Agent 系统** = 多个独立的 AI Agent 各司其职，通过通信和协作完成复杂任务。每个 Agent 有自己的角色、工具集、决策偏好。

```
单一 Agent:                          多 Agent:
┌──────────────┐              ┌──────────┐ ┌──────────┐ ┌──────────┐
│ 全能剪辑 Agent│              │ 搜索 Agent│ │ 策划 Agent│ │ 审核 Agent│
│    做所有事  │              │ "找出所有  │ │ "设计叙事  │ │ "检查逻辑  │
│              │              │  相关素材" │ │  结构"    │ │  和事实"  │
│  问题:       │              └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
│  1. 不够专注 │                   │              │              │
│  2. 无制衡   │                   └──────────────┼──────────────┘
│  3. 难扩展   │                                  │
└──────────────┘                     ┌────────────▼────────────┐
                                    │   编排 Agent             │
                                    │   "协调分工、汇总结果"    │
                                    └─────────────────────────┘
```

## 为什么需要多个 Agent

视频剪辑天然适合多 Agent：

1. **不同风格需要不同"人格"**：
   - "快节奏 Agent"：偏好短片段、快速切换、高能量
   - "情感向 Agent"：偏好长镜头、特写、情绪铺垫
   - "数据向 Agent"：偏好事实陈述、条理清晰、逻辑严密

   这些风格不是"调一个参数"，而是完全不同的素材选择和叙事编排策略。一个 Agent 很难同时做好三种风格。

2. **复杂任务需要分工**：策划一个 10 分钟的深度解说视频 = 搜索 50 段素材 + 设计 8 段叙事 + 写 2000 字脚本 + 审核事实准确性。单个 Agent 的上下文窗口和推理能力都不够。

3. **创作需要制衡**：Agent 容易陷入"确认偏误"——选了前几条结果就往下写，忽略了更好的素材。另一个 Agent 来审核和质疑，能打破这种偏误。

## 关键概念

### 1. 常见的多 Agent 架构

| 模式 | 描述 | VibeCut 场景 |
|------|------|-------------|
| **Supervisor** | 一个编排 Agent 给多个 Worker Agent 分配任务 | 策划任务分解：搜索 → 写作 → 审核 |
| **Debate** | 两个 Agent 对同一问题给出不同方案，辩论后选优 | 同一主题，快节奏 vs 情感向各出一个方案 |
| **Hierarchy** | Agent 层层上报，高层 Agent 做更宏观的决策 | 素材 Agent → 段 Agent → 片 Agent |
| **Market** | Agent 竞标任务，出价（质量承诺）最高的中标 | 多个搜索 Agent 各自搜一个角度 |

### 2. VibeCut 的多 Agent 愿景

```
用户: "剪一个关于 X 的 60 秒视频"
  ↓
编排 Agent (Orchestrator):
  ├─→ 搜索 Agent 1: "搜 X 的核心概念示例"  → 返回 8 条高相关性内容
  ├─→ 搜索 Agent 2: "搜 X 的情感高光时刻"  → 返回 5 条冲突/转折场景
  ├─→ 搜索 Agent 3: "搜 X 的反面案例"      → 返回 3 条对照素材
  ↓
策划 Agent: 综合三条搜索结果 → 设计叙事结构 (4 段，总 60 秒)
  ↓
写作 Agent: 为每段写脚本 (hook + 主体 + 转场)
  ↓
审核 Agent (Debate 模式):
  ├─→ 快节奏 Agent: "第 2 段太慢，建议砍掉前 3 秒"
  └─→ 情感向 Agent: "第 2 段的铺垫是必要的，但可以把语速提高"
  ↓
编排 Agent: 综合审核意见 → 修改脚本 → 导出
```

### 3. Agent Debate（辩论模式）

```
┌───────────────────┐     ┌───────────────────┐
│   Agent A         │     │   Agent B         │
│   (快节奏风格)     │     │   (情感向风格)     │
│                   │     │                   │
│ 方案: 5段, 每段12秒│     │ 方案: 3段, 每段20秒│
│ 开场: 冲突画面直入  │     │ 开场: 人物特写铺垫  │
│                   │     │                   │
└────────┬──────────┘     └────────┬──────────┘
         │                         │
         │    ┌──────────────┐     │
         └───→│  Debate      │←────┘
              │  (LLM Judge) │
              │              │
              │ "Agent A的前三段更好，但Agent B的结尾更感人。
              │  建议: 用A的开场+B的结尾，总时长65秒。" │
              └──────────────┘
```

这种方式在创意工作中特别有效——两个 Agent 从不同视角提供了不同的方案，Judge Agent 可以在它们之间做 trade-off。

### 4. Agent 并发

```python
import asyncio

async def multi_agent_search(topic):
    # 三个搜索 Agent 并行启动
    angles = [f"{topic} 核心概念", f"{topic} 反面论证", f"{topic} 情感故事"]
    tasks = [search_agent.run(angle) for angle in angles]
    results = await asyncio.gather(*tasks)

    # 综合结果
    return synthesize_agent.run(topic, results)
```

并发是关键——如果三个搜索 Agent 串行执行，用户要等 3 倍时间。并行执行的总时间 = 最慢的那个 Agent 的时间。

## 在 VibeCut 中的应用（远期规划）

当前 VibeCut 是单 Agent 架构——`run_pipeline()` 或 `story_first_pipeline()` 一个函数走到底。多 Agent 在远期路线图中：

- **阶段 1**（规划中）：将 `run_pipeline` 拆分为 Search Agent + Write Agent + Review Agent
- **阶段 2**（远期）：引入多风格 Agent 辩论机制
- **阶段 3**（远期）：用户可自定义 Agent 风格（"我的剪辑偏好：快节奏、信息密集、少煽情"）

## 前置知识

- [[Agent核心概念]] — 单 Agent 的工作原理
- [[Agent-First方法论]] — Capability Boundary Map 在多 Agent 场景下更重要
- [[人机协作HITL]] — 多 Agent 的辩论结果仍需人类最终确认

## 延伸

- [[Agent自我学习]] — 从多 Agent 辩论中学习哪些风格/策略更有效
- [[Agentic-RAG]] — 多个搜索 Agent 的并行检索
- [[LangGraph框架]] — LangGraph 的 multi-agent 支持

## 学习资源

- CrewAI 官方文档 — 多 Agent 协作框架
- AutoGen (Microsoft) — 多 Agent 对话模式
- LangGraph 官方文档: Multi-Agent Patterns
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 多 Agent 设计
