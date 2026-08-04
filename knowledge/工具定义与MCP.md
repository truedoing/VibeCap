---
title: 工具定义与MCP
type: topic
tags: [framework, technique, planned]
difficulty: 进阶
prerequisites: ["Agent核心概念", "大语言模型LLM"]
status: planned
created: 2026-08-04
---

# 工具定义与 MCP

> Agent 的手和脚 — 标准化的工具接口让 Agent 能操作真实世界

## 什么是 Tool

在 Agent 系统中，**Tool（工具）** 是 Agent 可以调用的外部功能。Agent 通过 Tool 来"操作世界"——搜索素材、读取文件、导出草稿。

```
Agent: "我需要搜一下苏大强在老宅的戏"
  → 决定调用 search_tool
  → 传入参数: {query: "苏大强 老宅", limit: 5}
  → 工具执行: BGE 搜索
  → 返回结果: [{ep: 1, start: 120, ...}, ...]
  → Agent 继续: "找到了5个，选第2个做开场"
```

## Tool 的三要素

一个标准 Tool 包含：

| 要素 | 说明 | 示例 |
|------|------|------|
| **名称** | Agent 用它来识别和选择工具 | `semantic_search` |
| **描述** | Agent 用它判断什么情况下该用这个工具 | "在已索引的VLM/ASR素材中搜索" |
| **Schema** | 工具接受的参数及其类型 | `{query: str, limit: int, mode: str}` |

**关键设计原则：** 描述的质量决定 Agent 能否正确地选择和使用工具。描述要写清楚"什么时候用"而不只是"是什么"。

## VibeCut 的工具规划

| 工具 | 封装现有模块 | 输入 | 输出 |
|------|------------|------|------|
| `semantic_search` | `_semantic_search()` | query, mode, limit | ClipRef[] |
| `browse_content` | `classify_transcript` 产出 | project_name | 内容摘要 |
| `analyze_transcript` | `_handle_analyze_transcript` | 文本 | 结构化分析 |
| `generate_storyboard` | `_generate_storyboard` | 解说词 | 视觉描述[] |
| `refine_segments` | `refine_segments.py` | segments, utterances | sub_clips |
| `export_capcut` | `export_capcut.py` | segments | 草稿路径 |

## MCP (Model Context Protocol)

MCP 是 Anthropic 提出的**工具接口标准协议**。类似于 USB-C 统一了设备接口，MCP 统一了 AI 工具的接口。

### 为什么需要 MCP

```
不用 MCP:                            用 MCP:

每个 Agent 框架有自己的工具格式:       所有框架共享同一种工具格式:
                                       
LangChain: @tool decorator            MCP Server
CrewAI:    BaseTool class               ├── tools/list (工具发现)
OpenAI:    function calling schema       ├── tools/call (工具调用)
                                        └── 任何框架都能消费
Agent A只能用自己的工具格式
Agent B只能用另一种格式                一次定义，到处使用
```

### MCP 在 VibeCut 中的意义

当前 VibeCut 只有一个工具（BGE 搜索），通过 `set_search_fn()` 全局注入。当工具数量增长到 10+ 个时，这种模式无法维护。

MCP 的价值在于：
1. **工具发现：** Agent 自动知道有哪些工具可用（而不是硬编码在 prompt 里）
2. **进程隔离：** 每个工具是独立的 MCP Server 进程，崩溃不影响其他工具
3. **生态复用：** 社区的 MCP Server（ffmpeg、filesystem）可以直接用

### VibeCut 的 MCP 演进路径

```
Phase 1 (当前): 函数注入
  set_search_fn(_agent_search)

Phase 2 (短期): LangChain @tool decorator
  @tool def semantic_search(...)

Phase 3 (长期): MCP Server
  vibecut-mcp-bge-search (独立进程)
  vibecut-mcp-ffmpeg
  vibecut-mcp-export
```

## 前置知识

- [[Agent核心概念]] — 工具是 Agent 三要素之一
- [[LangGraph框架]] — LangGraph 的 ToolNode 消费工具定义

## 延伸

- [[人机协作HITL]] — 有些"工具"其实是"等人类确认"
- [[Agent自我学习]] — Agent 可以学习"什么时候用哪个工具效果最好"

## 学习资源

- MCP 官方规范 (modelcontextprotocol.io)
- LangGraph ToolNode 文档
- `docs/tech/AGENT_ARCHITECTURE.md` — VibeCut 的 Tool 层设计
