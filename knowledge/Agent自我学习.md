---
title: Agent自我学习
type: topic
tags: [concept, frontier]
difficulty: 前沿
prerequisites: ["Agent核心概念", "人机协作HITL"]
status: frontier
created: 2026-08-04
---

# Agent 自我学习

> Agent 从每次剪辑中学习，下次做得更好

## 是什么

Agent 自我学习 = 从人类反馈和历史结果中持续改进自己的决策。不是重新训练模型，而是调整策略参数、更新偏好权重、积累成功案例。

## 三个学习层次

### Level 1: 偏好学习
Agent 观察人类修改了什么 → 提取模式 → 自动应用。

```
人类总是把 >10s 的 hook 缩短
  → Agent 学到: "用户偏好简短开场"
  → 下次默认生成 6-8s 的 hook
```

### Level 2: 质量反馈
人类对精切结果做修改 → Agent 分析被改掉的 sub_clips → 调整 KEEP/CUT 规则。

```
人类把 3 个 KEEP 改成 CUT (都是 host 说话)
  → Agent 学到: "host 引导语即使 layer=guide 也应该降低 KEEP 概率"
```

### Level 3: 跨任务知识迁移
Agent 从历史成片的完播率、用户评分中学习。

```
数据冲击型开场 → 完播率高
情感向收尾 → 用户评分高
  → Agent 学到: "数据冲击 + 情感收尾 组合效果好"
```

## 技术基础

- **偏好存储:** SQLite 存储历史偏好向量
- **模式识别:** LLM 分析修改记录，提取 pattern
- **策略调整:** 动态修改 planning prompt 中的默认参数

## 前置知识

- [[Agent核心概念]] — Agent 的基础能力
- [[人机协作HITL]] — 人类反馈是学习信号来源

## 学习资源

- RLHF (Reinforcement Learning from Human Feedback) — ChatGPT 的训练方法
- DSPy — "编译" prompt 而非手写
