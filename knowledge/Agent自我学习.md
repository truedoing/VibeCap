---
title: Agent自我学习
type: topic
tags: [concept, frontier]
difficulty: 前沿
prerequisites: ["Agent核心概念", "人机协作HITL", "多Agent协作"]
status: frontier
created: 2026-08-04
---

# Agent 自我学习

> Agent 的终极形态：不是每次从零开始，而是从人类的每一次修改中学习，越用越懂你。

## 是什么

**Agent 自我学习** = Agent 从用户的反馈和修改中提取偏好模式，自动调整后续行为。不需要用户显式配置"我喜欢快节奏"，而是 Agent 观察到你每次都把 15 秒的段剪成 10 秒，就学会了。

```
传统 Agent:                         自学习 Agent:
每次任务从零开始                    第 1 次: 和传统一样
用户手动修改输出                    用户改了 3 处 → Agent 记录偏好
下次还是同样的错误                  第 2 次: 自动应用上次的偏好
                                  用户又改了 1 处 → Agent 更新模型
                                  第 5 次: 几乎不需要修改
```

## 为什么需要自我学习

VibeCut 的核心矛盾：**AI 永远无法在第一次就命中用户的偏好**。

- 用户 A 喜欢 3 秒 hook（钩子），用户 B 喜欢 5 秒铺垫
- 用户 A 偏好信息密集的脚本，用户 B 偏好有节奏停顿
- 用户 A 喜欢用冲突画面做开场，用户 B 喜欢用人物特写

传统方案：给一堆配置项让用户调。但问题是——用户自己也不知道怎么描述自己的偏好。**行为比语言更诚实**：用户手动把 hook 从 5 秒剪到 3 秒 → 这就是偏好信号。

## 关键概念

### 1. Preference Learning（偏好学习）

```
反馈来源                  学习的内容
─────────────────────────────────────────────
用户调短了某段的时长      → "这个用户偏好更紧凑的节奏"
用户把 KEEP 改成 CUT      → "这个类型的 filler 应该默认剪掉"
用户调整了段的顺序        → "这个用户偏好这种叙事顺序"
用户替换了某段素材        → "这个搜索策略可能不对，下次换角度"
用户什么都没改就导出      → "全对！这些决策都是好的"
用户改完又改回来          → "不确定的偏好，降低权重"
```

每条反馈都是一条训练信号。不需要显式评分（"请给这次剪辑打分 1-5"）——用户的编辑操作本身就是评分。

### 2. 反馈循环

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌─────────┐
│ Agent   │ →   │  用户    │ →   │  对比    │ →   │ 更新    │
│ 生成方案│     │ 修改方案  │     │ 差异提取  │     │ 偏好模型 │
└─────────┘     └──────────┘     └──────────┘     └─────────┘
      ↑                                                   │
      └───────────────────────────────────────────────────┘
                      下次任务自动应用
```

这个循环每次任务跑一圈。第 1 次：Agent 生成 → 用户改了 5 处 → 提取 5 条偏好信号 → 更新模型。第 2 次：Agent 应用上次的偏好 → 用户只改了 2 处 → 提取 2 条信号 → 更新模型。循环收敛：用户修改越来越少。

### 3. RLHF 概念（用于剪辑）

RLHF（Reinforcement Learning from Human Feedback）在 LLM 领域是用来对齐模型和人类偏好的技术。它的核心思想完全适用于剪辑 Agent：

```
标准 RLHF（LLM 训练）:               剪辑 Agent 的 RLHF:
人类标注员比较两个回答               用户比较 Agent 生成的方案 vs 自己改的方案
  → 训练 Reward Model                  → 训练偏好模型
  → PPO 强化学习优化 LLM               → 下次策划时加权偏好
```

但在 VibeCut 的场景下，不需要完整的 PPO 训练。用更轻量的方法：

```python
# 轻量偏好模型：规则 + 加权
preferences = {
    "hook_duration": {"preferred": 3.0, "confidence": 0.8},    # 偏好 3 秒开场
    "segment_pace": {"preferred": "fast", "confidence": 0.9},  # 偏好快节奏
    "filler_tolerance": {"preferred": "low", "confidence": 0.95}, # 几乎不容忍废话
    "transition_style": {"preferred": "sharp", "confidence": 0.5}, # 不确定
}
```

`confidence` 是关键——Agent 只对高置信度的偏好自动应用，低置信度的偏好仍然展示给用户选择。

### 4. 用户画像

多个偏好组合成"用户画像"：

```python
user_profile = {
    "id": "user_001",
    "style": {
        "pace": "fast",           # 快节奏（置信度 0.9）
        "emotion": "balanced",    # 情感适中（置信度 0.6）
        "density": "high",        # 信息密集（置信度 0.85）
    },
    "patterns": [
        {"rule": "hook < 5s", "source": "edited 8/10 hooks shorter"},
        {"rule": "cut_all_filler", "source": "CUT 95% of filler segments"},
        {"rule": "prefer_conflict_openings", "source": "7/10 edits started with conflict"},
    ],
    "edits_count": 45,  # 总修改次数（越多越可信）
}
```

画像随使用次数增长。第 1 次任务：没有画像，Agent 用默认设置。第 50 次任务：画像已经相当准确，Agent 几乎不需要用户修改。

## 在 VibeCut 中的应用（远期规划）

当前状态：Agent 完全没有学习能力。每次任务从零开始，用户的手动修改不会被记录。

远期愿景：

```
阶段 1 — 偏好记录 (v1.5):
  记录用户每次精切时的 KEEP→CUT 或 CUT→KEEP 修改
  → 下次精切时参考历史偏好

阶段 2 — 自适应参数 (v2.0):
  hook_duration、segment_pace、filler_tolerance 自动调整
  → 每次策划时注入偏好参数到 system prompt

阶段 3 — 完整用户画像 (v3.0):
  多维度偏好模型 + confidence + decay（过时偏好自动降权）
  → Agent 在策划前先读用户画像，生成个性化方案
```

数据结构规划：

```python
# SQLite 新表: user_preferences
{
  "task_id": "0801学习新东方",
  "original_segment": {...},  # AI 原始输出
  "user_modified": {...},     # 用户修改后
  "diff_summary": "hook从5s→3s, 第3段KEEP→CUT",
  "timestamp": 1722768000
}
```

## 前置知识

- [[Agent核心概念]] — Agent 的基础架构
- [[人机协作HITL]] — 人类的修改是偏好信号的来源
- [[多Agent协作]] — 不同 Agent 可以学习不同的风格偏好

## 延伸

- [[Agent-First方法论]] — Log as Documentation：日志是偏好学习的训练数据
- [[SQLite数据层设计]] — 偏好数据如何存储

## 动手实验

设计一个简单的偏好追踪实验：

```python
# 模拟 5 次任务的 hook 时长偏好学习
tasks = [
    {"ai_hook": 5.0, "user_hook": 3.0},  # 用户缩短了
    {"ai_hook": 5.0, "user_hook": 3.5},  # 用户缩短了
    {"ai_hook": 4.0, "user_hook": 4.0},  # 用户没改
    {"ai_hook": 5.0, "user_hook": 2.5},  # 用户大幅缩短
    {"ai_hook": 3.0, "user_hook": 3.0},  # AI 猜对了
]

# 简单学习：取用户修改的平均值
user_preferred = sum(t["user_hook"] for t in tasks) / len(tasks)
ai_average = sum(t["ai_hook"] for t in tasks) / len(tasks)
print(f"AI 默认: {ai_average:.1f}s → 用户偏好: {user_preferred:.1f}s")
# → 下次 AI 应该用 {user_preferred:.1f}s

# 进阶：加权平均（越近的任务权重越高）
weights = [0.1, 0.15, 0.2, 0.25, 0.3]  # 指数衰减
weighted = sum(t["user_hook"] * w for t, w in zip(tasks, weights))
print(f"加权偏好: {weighted:.1f}s")
```

## 学习资源

- Anthropic: "Building Effective Agents" (2024.12) — Agent 自我改进设计原则
- RLHF 原始论文: "Training Language Models to Follow Instructions with Human Feedback"
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 自学习系统详细设计
