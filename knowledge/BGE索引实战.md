---
title: BGE索引实战
type: topic
tags: [technique, implemented]
difficulty: 中等
prerequisites: ["文本嵌入与语义向量", "向量检索与索引"]
status: implemented
created: 2026-08-04
---

# BGE 索引实战

> VibeCut 的核心知识库构建流程：从原始 ASR/VLM 数据到可搜索的语义索引文件。

## 是什么

**BGE 索引** = 用 BAAI/bge-base-zh-v1.5 模型，把 VibeCut 项目中的所有文本数据（ASR 对话、VLM 画面描述、字幕）编码为 768 维向量，保存为可快速检索的索引文件。

这条管线的入口是一个命令：

```bash
# 电视剧
python3 cli/build_index.py --project 都挺好

# 口播
python3 cli/build_index.py --project 杨老师教育
```

`cli/build_index.py` 自动检测项目类型（`projects/xxx.json` 中的 `type` 字段），走不同的索引策略。

## 为什么需要专门的构建脚本

几个不明显的复杂性：

1. **多数据源整合**：VLM 画面描述、ASR 对话、字幕三条独立的 JSON 线，需要合并成统一索引
2. **分块策略不同**：电视剧用场景边界，口播用说话人边界
3. **质量过滤**：VLM 的片头曲场景要跳过，ASR 短于 8 字符的碎片也要跳过
4. **双格式保存**：pickle（兼容）+ npy+json（mmap 高性能）
5. **降级策略**：清洗版数据不存在时自动降级到原始数据

## 关键概念

### 1. 电视剧索引 vs 口播索引

**电视剧 (`build_drama_index`)**：

```
数据源: VLM scene descriptions + scene subtitles + ASR transcripts
分块策略: 按场景 (每场景一条 VLM description + 字幕)
过滤规则:
  - skip_opening: 丢弃片头曲场景
  - VLM description < 10 字符: 丢弃
  - ASR text < 8 字符: 丢弃（太短没意义）
  - subtitle < 3 字符: 丢弃

编码量: 46集 ≈ 10-17万条 → 约 500MB npy
```

VLM 是数据主力——每一句画面描述都对应一个有时间边界的具体场景。ASR 补充对话信息。两者合并编码后，用户既可以通过描述搜画面，也可以通过关键词搜对话。

**口播 (`build_interview_index`)**：

```
数据源: classified_enhanced.json (guest-only, content+guide layer)
分块策略: 说话人边界 (speaker 切换时断句) + 时长边界 (>15秒断句)
过滤规则:
  - speaker = host: 全部不进入索引
  - layer = filler/meta: 不进入索引
  - cleaned_text < 2 字符: 丢弃
增强策略:
  - 同一说话人的连续语句聚合成 text 段 (最长 15 秒)
  - 编码 cleaned_text (LLM 清洗后), 返回 original_text (ASR 原文)

编码量: 1次采访 ≈ 200-500条 → 约 2MB npy
```

口播的核心规则：**只索引 guest（嘉宾）说的，而且是 content/guide 层的实质内容**。host（主持人）的话不索引——你搜"学习方法"，应该找到嘉宾的讲解，而不是主持人的引导语。

### 2. 分块策略细节

```python
# 口播分块：同一说话人连续语句合并
for seg in sorted(indexable, key=lambda s: s.get('start_sec', 0)):
    speaker = seg.get('speaker', 'guest')

    if last_speaker and speaker != last_speaker and chunk_texts:
        # 说话人切换 → 断句，编码当前 chunk
        merged = " ".join(chunk_texts)
        texts.append(merged)
        metas.append({"start": chunk_start, "end": ..., "text": merged,
                       "original_text": " ".join(chunk_originals)})
        chunk_texts = []  # 重置
        chunk_start = None

    # 时长边界：超过 15 秒也断句（避免单条太长导致检索不精确）
    seg_end = seg.get('start_sec', 0) + max(len(cleaned) // 5, 3)
    if seg_end - chunk_start >= 15 or len(chunk_texts) >= 5:
        merged = " ".join(chunk_texts)
        texts.append(merged)
        metas.append({...})
        chunk_texts = []
```

权衡：分块太大 → 搜索返回的片段太长，不精确。分块太小 → 语义信息不足，搜索不准确。15 秒是一个经验值。

### 3. 双格式保存

```python
def save_index(project_dir, embeddings, metas, texts):
    # 格式 1: pickle（兼容旧版，可一次性加载）
    with open("semantic_index.pkl", "wb") as f:
        pickle.dump({"embeddings": ..., "metas": ..., "texts": ...}, f)

    # 格式 2: npy + json（mmap 零拷贝，生产环境用）
    np.save("semantic_embeddings.npy", embeddings.astype(np.float32))
    with open("semantic_metas.json", "w") as f:
        json.dump(metas, f, ensure_ascii=False)
```

加载时的优先级（`routers/_lifespan.py` startup()）：
```python
if INDEX_NPY.exists() and INDEX_META.exists():
    semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')  # 优先 mmap
    semantic_metas = json.load(open(INDEX_META))
elif INDEX_FILE.exists():
    old = pickle.load(open(INDEX_FILE, "rb"))  # pickle 兜底
    semantic_emb = old["embeddings"]
    semantic_metas = old["metas"]
```

如果你想修改索引格式（比如加字段），只需要改 save + load 两处。

### 4. 离线模式与 HF Mirror

```python
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")     # 中国镜像
os.environ.setdefault("HF_HUB_OFFLINE", "1")                      # 离线模式
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")                 # 离线模式

model = SentenceTransformer("BAAI/bge-base-zh-v1.5",
                           local_files_only=True)  # 不联网
```

首次构建时需要联网下载模型（走 hf-mirror.com 国内镜像），后续构建时 `HF_HUB_OFFLINE=1` + `local_files_only=True` 确保不联网也能工作。

## 在 VibeCut 中的应用

**`cli/build_index.py`**：
- `build_drama_index()`（L16）— 电视剧索引（VLM + ASR 字幕 → BGE）
- `build_interview_index()`（L109）— 口播索引（说话人边界分块，guest-only）
- `save_index()`（L183）— 统一保存（pickle + npy + json）
- `main()`（L199）— 入口（自动检测类型、分发）

**`routers/_lifespan.py`**：
- `startup()`（L49-65）：索引加载（npy mmap 优先 → pickle 兜底）


## 动手实验

1. **观察索引文件大小**

```bash
ls -lh 杨老师教育/semantic_*
# semantic_embeddings.npy: 向量矩阵
# semantic_metas.json:    元数据（时间戳、类型、原始文本）
# semantic_index.pkl:     完整 pickle（embeddings + metas + texts）
```

2. **手写一个小规模的索引构建**

```python
from sentence_transformers import SentenceTransformer
import numpy as np

texts = ["苏大强在老宅里翻存折", "明玉站在办公室窗前打电话",
         "一家人在餐厅吃团圆饭", "苏明成在车库里打架"]
model = SentenceTransformer("BAAI/bge-base-zh-v1.5")
embeddings = model.encode(texts, normalize_embeddings=True)

np.save("mini_index.npy", embeddings.astype(np.float32))
print(f"索引: {embeddings.shape}")

# 搜索
query_emb = model.encode(["老宅找东西"], normalize_embeddings=True)[0]
scores = np.dot(embeddings, query_emb)
print(f"最佳匹配: '{texts[np.argmax(scores)]}' 得分: {max(scores):.3f}")
```

## 前置知识

- [[文本嵌入与语义向量]] — BGE 模型的工作原理
- [[向量检索与索引]] — 索引的加载和搜索
- [[语音识别ASR]] — 索引的数据来源之一

## 延伸

- [[混合搜索策略]] — 索引建成后的搜索策略
- [[RAG核心概念]] — BGE 索引是 RAG 的"知识库"
- [[模型部署与优化]] — HF 离线模式、镜像站等部署技巧
- [[SQLite数据层设计]] — 索引元数据入库到 index_entries
