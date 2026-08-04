---
title: 人机协作HITL
type: topic
tags: [concept, technique, planned]
difficulty: 进阶
prerequisites: ["Agent核心概念", "LangGraph框架"]
status: planned
created: 2026-08-04
---

# 人机协作 (HITL)

> Human-in-the-Loop：Agent 不是神，它在关键节点停下来，等人类确认。这不是"不够智能"，这是"负责任的设计"。

## 是什么

HITL（人机协作）是一种 AI 系统设计模式：在 Agent 自主执行过程中，关键决策节点会暂停执行，等待人类审批或修正，然后从断点继续。

```
完全手动:                         完全自动:
人类点击 10 次按钮                 输入一句话 → 输出成品视频
  ← VibeCut 现在卡在这                  ← 太危险，质量不可控

HITL (人机协作):
  Agent 自动完成 80% → 关键节点暂停 → 人类确认 → Agent 继续
                                             ↙
                                     人类拒绝 → Agent 修正
```

## 为什么完全自主是危险的

以视频剪辑为例：

1. **审美不可编码**：什么是"好的剪辑节奏"？人类都无法用算法描述，更别说 LLM 了。
2. **版权与合规**：Agent 可能选中了受保护的背景音乐，或者截取了一段容易引起争议的台词。
3. **叙事连贯性**：Agent 可能选出 5 段技术上"匹配主题"的片段，但拼在一起逻辑错乱。
4. **事实准确性**：LLM 生成的解说词可能张冠李戴（"苏大强"说成"苏明成"）。

**HITL 的核心思想：不要求 Agent 做对每一个决策，只要求它在不可逆的步骤前停下来。**

## 关键概念

### 1. 中断点 (Interrupt Points)

把 Agent 的执行流程画成一条线，在这些位置插入"中断点"：

```
[策划] → [搜索素材] → [生成脚本] → [人类: 脚本审核] → [修改] → [导出]
                        ↖ 中断点: 不通过就回去修改

[精切] → [标注 KEEP/CUT] → [人类: 精切审核] → [建轨] → [导出]
                                ↖ 中断点: 可手动调整 KEEP/CUT
```

### 2. LangGraph 的 interrupt() 机制

```python
from langgraph.checkpoint import interrupt

def review_node(state):
    # Agent 生成了脚本
    script = state["generated_script"]

    # 中断！等人类审批
    approval = interrupt({
        "message": "请审核以下脚本",
        "script": script,
        "options": ["approve", "reject", "modify"]
    })

    if approval == "approve":
        return {"status": "approved"}
    elif approval == "modify":
        return {"script": approval["modified_script"], "status": "revised"}
    else:
        return {"status": "rejected"}
```

`interrupt()` 做了什么：
1. 保存当前 state 到 checkpointer（SQLite）
2. 向客户端发送中断消息（通过 SSE）
3. 等待客户端发回审批结果
4. 恢复执行

**关键特性：服务器重启不会丢失状态。** 因为 state 已经持久化到数据库，重启后从断点继续。

### 3. 审批流

```
┌─────────────────────────────────────────────────┐
│                   Agent 执行                     │
│                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐   │
│  │ 策划     │ →  │ 搜索素材  │ →  │ 生成脚本  │   │
│  └──────────┘    └──────────┘    └─────┬────┘   │
│                                        │         │
│              ┌─────────────────────────┘         │
│              ▼                                   │
│       ┌─────────────┐                            │
│       │ 人类审批     │ ←── SSE 推送审批请求        │
│       │ 查看脚本     │                             │
│       └──┬───┬───┬──┘                             │
│          │   │   │                                │
│     approve reject modify                         │
│       │      │      │                             │
│       ▼      ▼      ▼                             │
│    导出   回到策划  修改后继续                      │
└─────────────────────────────────────────────────┘
```

### 4. HITL 的三种强度

| 强度 | 描述 | 适合场景 |
|------|------|---------|
| **L1 观察级** | Agent 执行，人类旁观。结果不满意就重来 | 实验阶段 |
| **L2 审批级** | 关键步骤暂停，等通过才继续 | 日常使用 |
| **L3 协作级** | Agent 生成多个方案，人类挑选或混合 | 创意工作 |
| **L4 教学级** | 人类教 Agent 怎么改，Agent 学习偏好 | 个性化 |

VibeCut 当前在 L1（人类看到结果后手动修改），规划中的 LangGraph 重构将带到 L2。

## 在 VibeCut 中的应用（规划）

当前 VibeCut 的"人机协作"还是手动的：

- **策划台**：AI 生成粗段脚本 → 人类手动编辑、排序、删除 → 点精剪按钮
- **精切预览**：AI 标注 KEEP/CUT → 人类翻看，不满意就回到策划台

规划升级后的流程：

```
POST /script/generate_story_first  (SSE)
  → Agent 策划
  → emit("review", {script: [...]})     ← 中断点 1
  → 等待人类审批 (approve / revise)

POST /script/refine  (SSE)
  → Agent 精切
  → emit("review", {sub_clips: [...]})  ← 中断点 2
  → 等待人类调整 KEEP/CUT

POST /export/capcut
  → 导出前最终确认 ← 中断点 3
```

每个中断点都能通过 LangGraph 的 `interrupt()` + Checkpointer 实现暂停和恢复。

## 为什么 HITL 对 VibeCut 特别重要

视频剪辑是典型的"AI 辅助 > AI 替代"领域：

- **不可逆操作太多**：导出错误的视频然后发现不对 = 浪费数小时
- **千人千面**：同一个主题，不同 up 主想要完全不同的剪辑风格
- **用户信任**：先让用户看到 AI 做好 80%，再让用户把关最后的 20%，比 AI 一把梭完（用户不信任）好得多

## 前置知识

- [[Agent核心概念]] — HITL 是 Agent 设计的关键模式
- [[LangGraph框架]] — LangGraph 的 interrupt() 和 Checkpointer 是实现 HITL 的基础设施
- [[HTTP服务与SSE流式]] — 中断和审批通过 SSE 实时推送

## 延伸

- [[Agent-First方法论]] — HITL 是渐进自主 (Progressive Autonomy) 的核心实践
- [[Agentic-RAG]] — Agent 驱动的检索也需要 HITL 把关

## 学习资源

- LangGraph 官方教程: Dynamic Breakpoints — interrupt() 的完整示例
- Anthropic: "Building Effective Agents" (2024.12) — HITL 最佳实践
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 的 HITL 详细设计
