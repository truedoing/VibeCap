---
title: 大语言模型LLM
type: topic
tags: [ai-model, technique, implemented]
difficulty: 中等
prerequisites: ["Python基础", "HTTP协议"]
status: implemented
created: 2026-08-04
---

# 大语言模型 (LLM)

> VibeCut 的"大脑"——所有需要理解和生成文本的地方都由 LLM 驱动

## 是什么

大语言模型（Large Language Model）是一个经过海量文本训练的神经网络，能理解自然语言指令并生成文本。在 VibeCut 中，DeepSeek-Chat 承担了策划、写作、审核、分类、清洗等多种角色。

## 为什么需要

剪辑视频需要大量的"理解"和"决策"：

- 理解 46 集电视剧的 ASR 文本中哪些片段与解说词相关
- 把用户输入的主题扩展为 5-8 段的叙事结构
- 判断一段 ASR 是"内容"还是"废料"
- 评估脚本质量并给出修改建议

这些不是规则能解决的——需要 LLM 的语言理解能力。

## 关键概念

### 1. System Prompt vs User Message

```
┌──────────────────────────────────┐
│ System Prompt (系统指令)          │
│ "你是一位短视频策划导演..."        │  ← 定义角色、规则、输出格式
│ 这部分不会被用户看到或修改          │
├──────────────────────────────────┤
│ User Message (用户输入)           │
│ "主题: 新东方的教育理念..."        │  ← 具体任务
│ 每次调用可以不同                   │
└──────────────────────────────────┘
```

### 2. Temperature（温度）

控制输出的"创造性"。0.0 = 确定性输出，1.0 = 高随机性。

VibeCut 中的选择：
- 策划/写作：0.3-0.4（需要创造性但不要乱编）
- 审核/分类：0.2-0.3（需要一致性）
- 闲聊：0.7（可以活泼）

### 3. JSON Mode（结构化输出）

**这是 VibeCut 最重要的 LLM 使用模式。** 普通 LLM 输出是自由文本，JSON Mode 强制输出结构化 JSON。

```
❌ 自由文本: "我觉得第一段应该用激将法开头，大概8秒..."
   → 无法用代码解析

✅ JSON Mode: {"sections":[{"role":"hook_tension","point":"...","duration":8}]}
   → 直接 json.loads() 使用
```

VibeCut 的每个 Agent 都依赖 JSON Mode。这也是 [[LangGraph框架|LangGraph]] 引入后 structured_output 要解决的问题——从"prompt 提示输出 JSON"升级为"类型系统保证输出 JSON"。

### 4. 上下文窗口 (Context Window)

LLM 一次能"看到"的最大文本量。DeepSeek-Chat 是 128K tokens（约 10 万字）。

VibeCut 利用这个窗口批量处理整段数据——`cli/clean_interview_data.py` 清洗整段口播转写、`lib/scene_map.py` 一次性为整集生成 scene_map（人物/地点/事件/情绪）。

### 5. API 调用模式

所有主流 LLM API（OpenAI、DeepSeek、MiMo）都遵循 **OpenAI 兼容格式**：

```
POST /v1/chat/completions
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "你是..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.4,
  "max_tokens": 3000
}
```

这意味着切换模型只需要改 `model` 字段和 `base_url`。

## 在 VibeCut 中的应用

| 模块 | LLM 角色 | System Prompt |
|------|---------|--------------|
| `handlers/prompts/script_drama.py`（SCRIPT_V2_PROMPT） | 编剧 V2 单 LLM | 反常识论点 + 起承转合 + 名场面 function（v2 放弃多 Agent，一次产出） |
| `lib/scene_map.py` | 场记 Agent | 生成 scene_map（人物/地点/事件/情绪）+ synopsis |
| `handlers/prompts/director.py`（DIRECTOR_PROMPT） | 导演 Agent | 解说词 → 叙事节拍 beats + 镜头查询 |
| `cli/classify_transcript.py` | 分类器 | 标注 layer (content/guide/meta/filler) |
| `cli/clean_interview_data.py` | 清洗器 | 清洗口语废词 + 识别说话人 |

## 前置知识

- HTTP API 调用（POST、JSON、Headers）
- 基础的 JSON 格式
- 什么是 Token（LLM 计费和处理的最小单位）

## 延伸

- [[LLM调用与工具使用]] — 从简单调用到 Tool Use 的进化
- [[Agent核心概念]] — LLM 如何从"回答问题"变成"自主行动"
- [[RAG核心概念]] — LLM + 检索 = 基于私有知识的生成

## 动手实验

```bash
# 用 curl 直接调 DeepSeek API
curl https://api.deepseek.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -d '{
    "model": "deepseek-chat",
    "messages": [
      {"role": "system", "content": "你是视频剪辑助手，用简洁中文回复"},
      {"role": "user", "content": "什么是hook开场？"}
    ]
  }'
```
