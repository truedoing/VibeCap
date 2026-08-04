---
title: LLM调用与工具使用
type: topic
tags: [technique, ai-model, planned]
difficulty: 中等
prerequisites: ["大语言模型LLM"]
status: planned
created: 2026-08-04
---

# LLM 调用与工具使用

> 从"LLM 回答问题"到"LLM 操作世界"的关键跃迁

## 是什么

**Function Calling（函数调用）/ Tool Use（工具使用）** 是 LLM 的一种能力：模型不直接输出文本，而是输出一个结构化的"我想调用这个函数，参数是这些"，然后由系统执行函数，把结果返回给模型。

## 为什么需要

VibeCut 的 Agent 需要搜索素材、分析文本、导出文件。这些不是 LLM 能直接做的——LLM 只能生成文本。Tool Use 让 LLM 能"用说的方式调用代码"。

## OpenAI 兼容格式

```json
{
  "model": "deepseek-chat",
  "messages": [...],
  "tools": [{
    "type": "function",
    "function": {
      "name": "semantic_search",
      "description": "在VLM/ASR素材库中搜索视频片段",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "limit": {"type": "integer", "default": 15}
        },
        "required": ["query"]
      }
    }
  }]
}
```

LLM 返回的不是文本，而是：
```json
{
  "tool_calls": [{
    "function": {"name": "semantic_search", "arguments": "{\"query\":\"苏大强 发火\"}"}
  }]
}
```

## LangChain @tool decorator

封装的声明式写法：
```python
from langchain_core.tools import tool

@tool
def semantic_search(query: str, limit: int = 15) -> list[dict]:
    """在VLM/ASR素材库中搜索视频片段。用于找特定角色、场景、情绪的镜头。"""
    return _search_impl(query, limit)
```

## 在 VibeCut 中的演进

| 阶段 | 方式 |
|------|------|
| 当前 | `_call_llm()` 纯文本调用，手动 `json.loads()` |
| Phase 1 | `@tool` decorator 声明工具 |
| Phase 2 | LangGraph ToolNode 让 Agent 自主调用 |
| Phase 3 | MCP 标准化工具协议 |

## 前置知识

- [[大语言模型LLM]] — Tool Use 是 LLM 的高级能力
- [[工具定义与MCP]] — 工具接口标准化
- [[Agent核心概念]] — Tool Use 是 Agent 三要素之一
