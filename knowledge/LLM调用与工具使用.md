---
title: LLM调用与工具使用
type: topic
tags: [technique, ai-model, planned]
difficulty: 中等
prerequisites: ["大语言模型LLM", "Agent核心概念"]
status: planned
created: 2026-08-04
---

# LLM 调用与工具使用

> Tool Use（函数调用）：让 LLM 不只是"说"，还能"做"。从生成文字到调用外部 API——这是 Agent 的手和脚。

## 是什么

**Function Calling / Tool Use** 是一种让 LLM 调用外部函数的能力。LLM 不直接执行函数——它输出一个结构化的"我想调用这个函数，参数是这些"的 JSON，由你的代码实际执行，然后把结果传回 LLM。

```
传统 LLM 调用:                      带 Tool Use 的 LLM 调用:
                                     ┌──────────┐
用户: "深圳今天天气?"       用户: "深圳今天天气?"    │ 天气 API │
  ↓                          ↓                    └─────┬────┘
LLM: "抱歉我不知道"    LLM: → 输出:                        │
                              {tool: "get_weather",  ┌────▼────┐
                               args: {city: "深圳"}}  │ 你的代码  │
                                                         │ 执行调用  │
                                                         └────┬────┘
                                                              │
                                    LLM ← 返回: {temp: 26,   │
                                              weather: "晴"}  │
                                      ↓
                                    LLM: "深圳今天晴天，26°C"
```

## 为什么 Tool Use 是关键能力

1. **突破 LLM 的知识边界**：LLM 不知道实时天气、不知道你的素材库里有什么——但通过 Tool Use，它可以"问"。

2. **从对话到行动**：没有 Tool Use，LLM 只是一个聊天机器人。有了 Tool Use，LLM 可以搜索、分析、导出、控制设备。

3. **Agent 的手和脚**：[[Agent核心概念]]中讲的"大脑(LLM) + 手脚(工具)"——Tool Use 就是那个"手脚"。

## 关键概念

### 1. OpenAI 兼容的工具调用格式

目前几乎所有 LLM API（包括 DeepSeek）都遵循 OpenAI 的工具调用协议：

```python
# 1. 定义工具 schema
tools = [{
    "type": "function",
    "function": {
        "name": "search_semantic",
        "description": "搜索视频素材库，返回相关片段时间和内容",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，建议用短句（5-15字）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 15
                }
            },
            "required": ["query"]
        }
    }
}]

# 2. 发送给 LLM（带 tools 参数）
response = requests.post("https://api.deepseek.com/v1/chat/completions", json={
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "搜索苏大强在老宅的片段"}],
    "tools": tools,
    "tool_choice": "auto"  # LLM 自行决定是否需要调用工具
})

# 3. LLM 返回 tool_call（而非直接回答）
# response.choices[0].message.tool_calls = [{
#     "function": {"name": "search_semantic", "arguments": '{"query": "苏大强 老宅"}'}
# }]

# 4. 你的代码执行搜索
result = your_search_function("苏大强 老宅")

# 5. 把结果传回 LLM
messages.append({"role": "tool", "content": json.dumps(result), "tool_call_id": "..."})
response2 = requests.post(API_URL, json={"messages": messages, ...})
# LLM 看着搜索结果，生成最终回答
```

### 2. 工具定义的三要素

| 要素 | 说明 | 示例 |
|------|------|------|
| `name` | 函数名（LLM 用这个来"叫"工具） | `search_semantic` |
| `description` | 自然语言描述（LLM 据此决定要不要用） | "搜索视频素材库..." |
| `parameters` | JSON Schema 格式的参数定义 | `{"query": {"type": "string"}, ...}` |

`description` 写得好不好，直接决定 LLM 会不会在正确的时机调用正确的工具。关键原则：**描述"这个工具做什么"，而非"怎么实现"**。

### 3. 从纯文本调用到 Tool Use

VibeCut 当前的 `_call_llm()` 用法（`script_agents.py` 第 69 行）是纯文本调用：

```python
def _call_llm(system_prompt, user_content, temp=0.4, max_tokens=3000):
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": temp, "max_tokens": max_tokens,
    }).encode()
    # ... 发送请求，返回纯文本
```

LLM 被当成一个"聪明一点的文本处理器"——输入 prompt，输出 JSON。这种方式的问题：

- LLM 不知道自己能搜索（搜索是外部代码手动调用的）
- LLM 不能主动决定"我需要搜一下"
- 所有编排逻辑在 Python 代码里，LLM 只是执行者

**升级路径**：将 `_call_llm()` 从纯文本调用升级为支持 tools 参数的 Tool Use 调用。这样 LLM 在生成脚本时可以主动调用搜索工具来补充素材。

### 4. @tool 装饰器模式（LangChain）

```python
from langchain.tools import tool

@tool
def search_semantic(query: str, limit: int = 15) -> list:
    """搜索视频素材库，返回相关片段时间和内容"""
    q_emb = model.encode(query)
    scores = np.dot(index, q_emb)
    # ... 返回 top-k 结果
    return results

@tool
def read_transcript(start: float, end: float) -> str:
    """读取指定时间范围内的完整 ASR 原文"""
    # ... 从索引中查找
    return transcript_text

# Agent 自动获得这两个工具
agent = create_react_agent(llm, [search_semantic, read_transcript])
```

`@tool` 装饰器自动把函数的 docstring 和类型注解转换为 Tool Definition schema。这让工具定义和工具实现放在一起，比手动写 JSON schema 方便很多。

## 在 VibeCut 中的应用（规划）

当前状态：
- `_call_llm()` 是纯文本调用，不支持 Tool Use
- Agent 的"工具"（搜索、导出）是外部代码在 Agent 之前/之后手动调用的
- ChatPanel 的搜索是前端直接调 `/search` API，LLM 不参与

规划升级：
- `_call_llm()` 升级为支持 `tools` 参数
- Agent 可以自主决定何时搜索、搜索什么
- 前端 ChatPanel 的搜索请求经过 Agent 决策层，而非直连搜索 API

## 前置知识

- [[大语言模型LLM]] — LLM 的工作原理
- [[Agent核心概念]] — Tool Use 是 Agent 三要素中的"手脚"
- [[工具定义与MCP]] — 工具标准化的 MCP 协议

## 延伸

- [[Agentic-RAG]] — Tool Use 应用于检索场景
- [[Agent-First方法论]] — Tool-First 实践：先定义工具，再设计流程
- [[多Agent协作]] — 不同 Agent 有不同的工具集

## 动手实验

用 DeepSeek API 手动测试一次 Tool Use：

```python
import requests, json

API_URL = "https://api.deepseek.com/v1/chat/completions"
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"}
            },
            "required": ["city"]
        }
    }
}]

resp = requests.post(API_URL, headers={
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    "Content-Type": "application/json"
}, json={
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "深圳今天天气怎么样？"}],
    "tools": tools,
    "tool_choice": "auto"
})

print(resp.json()["choices"][0]["message"])
# 应该能看到 tool_calls 字段，而非直接的文本回答
```

## 学习资源

- OpenAI Function Calling 官方文档 — Tool Definition schema 详细说明
- DeepSeek API 文档 — tool_choice 参数说明
- LangChain Tools 文档 — @tool 装饰器的完整用法
