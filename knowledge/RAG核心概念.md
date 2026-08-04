---
title: RAG核心概念
type: topic
tags: [technique, concept, implemented]
difficulty: 中等
prerequisites: ["文本嵌入与语义向量", "大语言模型LLM"]
status: implemented
created: 2026-08-04
---

# RAG 核心概念

> 检索增强生成 (Retrieval-Augmented Generation)：先搜再答，用外部知识补 LLM 的盲区

## 是什么

RAG 是一个三步骤模式：

```
用户提问 → 从知识库检索 → 把结果注入 Prompt → LLM 生成答案
  (1)         (2)               (3)                (4)
```

**为什么需要 RAG？** LLM 有两个根本局限：
1. **知识截止日期：** 训练数据有时间点，不知道之后的事
2. **幻觉：** 不知道的事会编造

RAG 不给 LLM "凭空回忆"，而是先找到相关资料，再让 LLM 基于资料回答。

## VibeCut 就是 RAG

```
VibeCut 的剪辑流程映射到 RAG:

传统 RAG:         VibeCut RAG:
──────────        ────────────
文档              视频 (通过 ASR/VLM 转为文本)
Chunking          说话人边界 / 时间窗口
Embedding          BGE-base-zh-v1.5
检索               语义搜索 + 关键词搜索
LLM 生成           Agent 生成脚本 + 精切
```

## 关键概念

### 1. Chunking (分块策略)

把长文档切成小块，每块独立编码。**Chunking 策略是 RAG 质量的第一决定因素。**

| 策略 | 怎么做 | 适合场景 |
|------|--------|---------|
| 固定窗口 | 每 500 token 一刀切 | 通用文档 |
| 递归分割 | 按段落→句子→词逐级切 | 结构化文档 |
| 语义分割 | 找语义断点再切 | 需要连贯语义 |
| **说话人边界** | 同一说话人连续说的一段 | VibeCut 口播 |
| **场景边界** | 同一个场景内的片段 | VibeCut 电视剧 |

### 2. Retrieval (检索)

从知识库中找到最相关的 N 个片段。不只是"向量搜索 Top-K"：

```
检索深度层级:

Level 1: Naive — 只做向量余弦相似度
Level 2: Hybrid — 向量 + 关键词 加权融合
Level 3: Rerank  — Cross-encoder 二次精排
Level 4: Multi-Step — 第一次检索 → LLM判断 → 第二次精确检索
Level 5: Agentic — Agent 自己决定搜什么、搜几次、怎么筛选
```

VibeCut 当前在 Level 2，正在向 Level 5 演进。

### 3. Augmentation (增强)

把检索结果填入 Prompt。关键是**如何在有限的 Token 窗口内放入最有价值的信息**：

| 模式 | 做法 | 适用 |
|------|------|------|
| Stuff | 全部塞进去 | 结果少 |
| Map-Reduce | 分批总结→汇总 | 结果多 |
| Refine | 逐条精炼 | 需要迭代 |
| Compact | 压缩后再塞 | Token 紧张 |

### 4. Generation (生成)

LLM 基于增强后的 Prompt 输出。关键在于 Prompt 里怎么引用检索结果：
- 带上来源标注：`[来源: EP5, 120s-135s]`
- 区分不同来源的可信度
- 让 LLM 知道"基于以下资料回答，没有的就说不确定"

## RAG 进化路线

```
Naive RAG ──→ Advanced RAG ──→ Agentic RAG
(已商品化)     (当前主流)        (前沿)

Chunk          +混合搜索         +Agent自主决策
+Embed         +Reranker         +多轮搜索
+向量搜索       +元数据过滤       +结果反思
+LLM生成       +Query改写        +策略调整
```

## 前置知识

- [[文本嵌入与语义向量]] — 文本怎么变向量
- [[大语言模型LLM]] — LLM 怎么调用
- [[向量检索与索引]] — 向量怎么搜索

## 延伸

- [[混合搜索策略]] — 向量搜索 + 关键词搜索怎么融合
- [[BGE索引实战]] — VibeCut 的 RAG 实现全貌
- [[Agentic-RAG]] — RAG 的下一步进化
- [[Agent核心概念]] — Agent + RAG 的结合

## 学习资源

- LlamaIndex 官方教程 (RAG 概念最清晰的入门)
- LangChain RAG 教程 (代码层面理解 RAG 各组件)
- `docs/tech/RAG_KNOWLEDGE.md` — VibeCut 项目内的深度分析
