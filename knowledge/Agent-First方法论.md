---
title: Agent-First方法论
type: topic
tags: [concept, methodology]
difficulty: 进阶
prerequisites: ["Agent核心概念", "人机协作HITL"]
status: planned
created: 2026-08-04
---

# Agent-First 方法论

> AFDD (Agent-First Driven Development)：不是"先写功能再交给 AI"，而是从第一天起就把 Agent 当作一等公民来设计系统。

## 是什么

Agent-First 是一种软件开发方法论：在设计系统时，把 AI Agent 视为一个**有自主决策能力的团队成员**，而非一段工具代码。架构、接口、错误处理——全部围绕 Agent 的感知-决策-行动循环来设计。

```
传统 Human-First:                     Agent-First:
用户点击按钮 → 执行功能 → 返回结果    Agent感知状态 → 自主决策 → 调用工具 → 汇报结果
     ↑ 人类驱动每一步                       ↑ 人类批准关键节点
     ↓ 系统被动响应                         ↓ Agent编排80%的工作
```

## 为什么需要 Agent-First

VibeCut 的现状很能说明问题：

1. **传统开发的局限性**：`run_pipeline()` 里硬编码了 5 个步骤的编排逻辑。每加一个新功能，就要修改编排代码。这不是"Agent 在决策"，而是"开发者替 Agent 做了所有决策"。

2. **维护成本爆炸**：当 pipeline 从 5 步变成 15 步，if-else 分支从 3 个变成 30 个——人类编写的编排逻辑无法扩展。

3. **AI 被当成工具链的一环**：LLM 被调用、返回 JSON、然后下一段代码处理 JSON。LLM 不知道上一步发生了什么，也不知道下一步该做什么。

Agent-First 的核心主张：**把编排权交给 Agent，人类退到审批位。**

## 5 大核心实践

### 实践 1：Agent Persona（角色定义）

不是"写一个 prompt"，而是定义一个完整的 Agent 角色：

```
VibeCut 策划 Agent:
- 身份: 资深影视剪辑策划
- 技能: 素材搜索、叙事结构设计、脚本压缩
- 约束: 单段 ≤ 15 秒，总时长 ≤ 90 秒
- 偏好: 情感张力优先于信息密度
```

在 VibeCut 中的应用：`handlers/prompts/director.py` 的 DIRECTOR_PROMPT、`handlers/prompts/script_drama.py` 的 SCRIPT_V2_PROMPT 定义了 Agent 的角色、能力和边界。

### 实践 2：Capability Boundary Map（能力边界图）

明确回答三个问题：

| 问题 | VibeCut 的回答 |
|------|---------------|
| Agent 能做什么？ | 搜索素材、设计叙事、标注精切 |
| Agent 不能做什么？ | 选背景音乐、调色、替换素材（不可逆操作） |
| 不确定时怎么办？ | 停下来，问人类（`interrupt()`） |

### 实践 3：Tool-First（工具优先）

先定义 Agent 能调用哪些工具，再设计思考流程。Agent 的"智能"来自它能使用多少好工具。

```
VibeCut Agent 工具箱:
├── search_semantic(query) → 搜索素材
├── read_transcript(start, end) → 读取原文
├── propose_segment(topic, clips) → 生成一段脚本
├── refine_segment(seg_id) → 精切标注
└── export_capcut(segments) → 导出剪映草稿
```

### 实践 4：Progressive Autonomy（渐进自主）

不追求一步到位全自动。先跑通 HITL L1（观察级），验证 Agent 在每个节点的输出质量，再逐步放开自主权。

```
L0: 完全手动（当前部分功能）
L1: Agent 执行，人类旁观（当前 run_pipeline）
L2: 关键步骤暂停，等人类审批（LangGraph interrupt，规划中）
L3: Agent 生成多方案，人类选择（远期）
```

### 实践 5：Log as Documentation（日志即文档）

Agent 的每一步决策都要留下结构化日志。这些日志不仅是调试工具，也是"Agent 的思考过程文档"。

```python
# VibeCut 的 Agent 日志格式
{
  "step": "search",
  "query": "苏大强 家庭矛盾",
  "results": 15,
  "top_score": 85.2,
  "decision": "选取前 5 条",
  "reasoning": "后 10 条相关性低于 0.25 阈值"
}
```

## 在 VibeCut 中的应用

当前 VibeCut 处于 Agent-First 的 L1-L2 混合阶段：

- **✅ Tool-First**：`lib/llm.py` 统一 LLM 调用；`handlers/storyboard.py`（导演Agent）编排 beats + 镜头匹配，`handlers/search.py` 供搜索复用
- **⚠️ Persona**：system prompt 有角色定义，但还不够系统
- **⚠️ Capability Map**：能力边界在代码中隐式存在，但未文档化
- **❌ Progressive Autonomy**：还没有 `interrupt()` 机制（规划中）
- **❌ Log as Doc**：SSE 流有状态输出，但非结构化日志

升级到 LangGraph 后，5 大实践将全部落实。

## 前置知识

- [[Agent核心概念]] — Agent 的三要素和 Agent Loop 是 Agent-First 的基础
- [[人机协作HITL]] — 渐进自主的核心实现机制
- [[LangGraph框架]] — Agent-First 的技术基础设施

## 延伸

- [[多Agent协作]] — 当系统里有多个 Agent 时，Agent-First 的复杂度升级
- [[Agent自我学习]] — Agent-First 的终极形态：Agent 从经验中自我改进
- [[Agentic-RAG]] — Agent-First 应用于检索增强生成

## 学习资源

- Anthropic: "Building Effective Agents" (2024.12) — Agent-First 设计的权威指南
- LangGraph 官方文档: Multi-Agent Patterns
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut Agent 架构详细设计
