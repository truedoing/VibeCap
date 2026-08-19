---
title: 文本切分与Chunking
type: topic
tags: [technique, concept, implemented]
difficulty: 中等
prerequisites: ["文本嵌入与语义向量", "RAG核心概念"]
status: implemented
created: 2026-08-19
---

# 文本切分与 Chunking

> 把长文本切成适合检索/喂给 LLM 的小块 —— RAG 质量的第一决定因素

## 为什么切分这么重要

Embedding 模型（如 BGE）有**输入长度上限**（VibeCut 的 BGE 约 512 token），且长文本嵌入会"稀释"语义——一段话里揉进太多内容，向量就不聚焦。

**Chunking 是 RAG 质量的第一决定因素**，因为：
1. **检索命中**：查询词要落在"语义单元"内才能被向量匹配到
2. **上下文完整性**：切得太碎，单块信息不完整，LLM 读不懂
3. **Token 成本**：每块都要嵌入 + 进 Prompt，块越多越贵

```
切得太大 → 语义稀释，检索不准
切得太小 → 单块信息残缺，生成质量差
切得合适 → 每块是一个完整语义单元
```

## Chunking 策略全景

### 1. 固定窗口（Fixed Window）

每隔 N 个 token 一刀切，可加 M 个 token 重叠。

```python
# 每 500 token 一刀，重叠 50
def fixed_window(text, size=500, overlap=50):
    return [text[i:i+size] for i in range(0, len(text), size - overlap)]
```

**优点**：简单、确定、可复现。**缺点**：可能把句子/语义切断。

### 2. 递归分割（Recursive Split）

按分隔符逐级切：段落 → 句子 → 短语 → 词。先按段落切，太长再按句子切，直到每块不超限。

**优点**：尊重文本结构，块边界自然。**缺点**：对无结构文本（口播转写）无效。

### 3. 语义分割（Semantic Chunking）

用向量相似度找"语义断点"——相邻句子的嵌入相似度骤降处就是切分点。

**优点**：切在语义边界。**缺点**：要计算所有相邻句对，慢。

### 4. 结构化边界（VibeCut 的核心）

**不用通用策略，直接用数据的天然边界：**

| 数据 | 边界 | 每块内容 |
|------|------|---------|
| 口播采访 | **说话人边界** | 同一说话人连续的一段话 |
| 电视剧 | **场景边界** | 同一个场景（scene_map time_range）内的片段 |
| 台词 | 字幕句 | 单句或语义成组的几句 |

```python
# VibeCut 电视剧：按 scene_map 的场景区间切
for scene in scene_map:
    block_text = [sub for sub in subtitles
                  if scene['time_range'][0] <= sub['start'] <= scene['time_range'][1]]
```

**为什么这样切最好：** LLM/检索要的"语义单元"恰好是"谁在哪说了什么"。说话人边界 = 一段连贯的陈述；场景边界 = 一个完整的事件。比固定窗口切出的块信息完整得多。

## Chunk 大小与重叠的权衡

| 因素 | 影响 |
|------|------|
| 块太小 | 信息残缺，检索到也答不全 |
| 块太大 | 语义稀释，检索不准 |
| 重叠 | 补边界信息，但增加 token 成本 |

**经验法则：** 块大小约等于"一个语义单元"（一段台词 / 一个场景），重叠只用于连续文档。VibeCut 的电视剧检索按场景（60-120s 的字幕），口播按说话人段。

## VibeCut 的三层切分实践

```
源视频
  ├─ 字幕 (subtitle_result.json)     ← 每句一条，天然细粒度
  ├─ scene_map (场景边界)            ← 场记Agent 切出 60-120s 的场景
  └─ 嵌入粒度                        ← 场景级文本 → BGE 向量
```

**关键教训：** 最初按固定窗口切 ASR，检索"苏明成打明玉"时命中零散台词，信息不完整；改成按 scene_map 场景切后，一个场景的完整冲突（起因-过程-后果）作为整体被检索，匹配质量显著提升。**数据本身的边界 > 通用的切分算法。**

## 与 Embedding 的配合

- 块文本 → 嵌入 → 存向量库（VibeCut: `semantic_embeddings.npy`）
- 检索时：查询向量 vs 所有块向量 → 余弦相似度 Top-K
- 返回的块连同它的元数据（EP/场景/时间）一起给 LLM

**VibeCut 里：** `cli/build_index.py` 把每个场景的字幕拼成一块，嵌入后存 npy；检索时 `handlers/search.py` 算余弦相似度，命中块带 `ep + 场景区间` 返回。

## 前置知识

- [[文本嵌入与语义向量]] — 切好的块怎么变成向量
- [[RAG核心概念]] — 切分在 RAG 流程中的位置

## 延伸

- [[混合搜索策略]] — 向量 + 关键词怎么配合
- [[BGE索引实战]] — VibeCut 索引构建全貌
- [[语音识别ASR]] — 口播转写后怎么按说话人切

## 学习资源

- LlamaIndex 文档 Chunking 章节
- "ChunkViz" 工具 — 可视化不同切分策略的效果
