---
name: vibecut-tech-stack
description: VibeCut 全栈技术清单 — 语言、框架、库、模型
metadata:
  type: reference
---

# VibeCut 技术栈

## 语言
- Python 3.12 (后端)
- JavaScript ES Modules (前端，JSX，非 TypeScript)

## 后端
- http.server + socketserver.ThreadingMixIn (HTTP 服务)
- SQLite WAL 模式 (vibecut.db)
- SSE (Server-Sent Events 流式响应)

## AI 模型
- BAAI/bge-base-zh-v1.5 (768维语义嵌入，本地CPU)
- faster-whisper small/base (本地ASR，int8量化)
- DeepSeek-Chat (云端LLM，128K上下文)
- MiMo v2.5 (云端VLM，画面分析)
- F5-TTS (实验性语音克隆)

## AI 框架/库
- sentence-transformers (BGE模型加载)
- numpy (向量计算 + mmap)
- CTranslate2 (faster-whisper推理后端)

## 前端
- React 19 + React Router 7
- Vite 8 (构建工具)
- Tailwind CSS 4
- Elah (@elah/editor, 视频编辑引擎)
- Radix UI (无障碍原语) + shadcn/ui 模式
- Zustand (Elah内部状态管理)

## 规划引入 (agent-arch 分支)
- langchain-core (类型系统)
- langchain-openai (LLM调用)
- LangGraph (Agent编排)

## 外部API
- DeepSeek API (api.deepseek.com)
- MiMo API (api.xiaomimimo.com)
- HuggingFace Hub (hf-mirror.com 国内镜像)

## 详见
- docs/tech/TECH_STACK.md — 完整技术架构文档

**Why:** 记录当前和规划中的完整技术栈，方便上下文切换时快速回忆。
**How to apply:** 技术决策参考此清单和 ADR 文档 (docs/tech/ARCHITECTURE_PHILOSOPHY.md)。

## 关联
- [[vibecut-project-overview]] — 项目概览
- [[vibecut-agent-upgrade-plan]] — Agent 升级计划
