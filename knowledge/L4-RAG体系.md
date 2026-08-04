---
title: L4-RAG体系
type: moc
tags: [moc, technique]
created: 2026-08-04
---

# L4: RAG 体系

> VibeCut 的核心检索能力 — 从 ASR/VLM 文本到可搜索的语义索引

## 本层知识点

| 笔记 | 主题 | 难度 | 状态 |
|------|------|------|------|
| [[RAG核心概念]] | RAG 定义、Chunking、检索模式 | 🟡 | ✅ |
| [[向量检索与索引]] | numpy mmap, 余弦相似度, Top-K | 🟡 | ✅ |
| [[混合搜索策略]] | 向量 + 关键词加权融合 | 🟡 | ✅ |
| [[BGE索引实战]] | VibeCut 完整索引构建流程 | 🟡 | ✅ |
| [[文本切分与Chunking]] | 固定窗口 vs 说话人边界 vs 语义切分 | 🟡 | 📝 |
| [[RAG评估方法]] | RAGAS, 检索质量量化 | 🔴 | 📅 |

## 为什么这层是 VibeCut 的核心竞争力

通用 RAG 框架（LangChain/LlamaIndex）解决的是文档问答。VibeCut 的 RAG 是**领域特化的视频素材检索**：

| 维度 | 通用 RAG | VibeCut RAG |
|------|---------|-------------|
| 数据源 | PDF/DOCX/TXT | 视频 (ASR+VLM → 文本) |
| Chunking | token 窗口 | 说话人/场景边界 |
| 检索目标 | 回答问题 | 找可剪辑的素材片段 |
| 评分 | 语义相似度 | 语义 + 时间多样性 + 叙事角色 |

## 与其他层的关系

```
L3 (AI基础层) ──→ L4 (RAG体系)
  BGE/LLM           │
                    ├──→ 索引构建: ASR/VLM文本 → BGE编码 → numpy存储
                    ├──→ 查询检索: 用户query → BGE编码 → np.dot → Top-K
                    └──→ LLM生成: 检索结果 → prompt注入 → 脚本生成
                         │
                         ▼
                    L5 (Agent系统)
                      Agent使用检索工具自主搜索素材
```

## 学习路径

```
起点: [[RAG核心概念]] — 理解 RAG 是什么
  ↓
[[向量检索与索引]] — 理解底层数学
  ↓
[[混合搜索策略]] — 理解为什么向量+关键词 > 纯向量
  ↓
[[BGE索引实战]] — 理解 VibeCut 的完整实现
  ↓
[[文本切分与Chunking]] — Chunking 策略决定检索质量上限
```
