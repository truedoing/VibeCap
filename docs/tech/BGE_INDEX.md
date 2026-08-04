# BGE 语义搜索索引 — 深度剖析

> 从构建到查询的完整技术链路

---

## 目录

1. [概述](#概述)
2. [技术选型](#1-技术选型)
3. [索引构建](#2-索引构建)
4. [索引加载](#3-索引加载)
5. [查询检索](#4-查询检索)
6. [电视剧 vs 口播 — 双模式对比](#5-电视剧-vs-口播--双模式对比)
7. [存储格式与性能](#6-存储格式与性能)
8. [数据流全景图](#7-数据流全景图)

---

## 概述

VibeCut 的核心检索能力基于 **BGE (BAAI General Embedding)** 语义搜索。它不是简单的关键词匹配，而是将所有素材文本（ASR 转写 + VLM 画面描述）映射到 768 维语义向量空间，查询时通过**余弦相似度**找到语义最相关的素材片段。

### 核心公式

```
similarity(query, doc_i) = dot(encode(query), embeddings[i])

     query_text ──→ BGE.encode() ──→ q_emb (768维, L2归一化)
     doc_texts  ──→ BGE.encode() ──→ emb_matrix (N×768, L2归一化)

     scores = emb_matrix @ q_emb       ← N次余弦相似度, 一次矩阵乘法
     top_k = argsort(scores)[-k:]      ← 取最高k个
```

### 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 索引存储 | 全量内存 | N < 10万，无需向量数据库 |
| 查询方式 | 矩阵乘法一次计算 | O(N×D) 在万级规模下 <10ms |
| 模型设备 | CPU | 无 GPU 依赖，部署简单 |
| 归一化 | L2 normalize | 余弦相似度退化为内积 |
| 离线模式 | `HF_HUB_OFFLINE=1` | 启动不访问网络 |

---

## 1. 技术选型

### 1.1 模型：BAAI/bge-base-zh-v1.5

| 属性 | 值 |
|------|-----|
| **架构** | BERT-base (12层 Transformer Encoder) |
| **参数量** | ~102M |
| **向量维度** | 768 |
| **最大序列长度** | 512 tokens |
| **训练语料** | 中文语料 + 检索任务微调 |
| **特殊处理** | Query 端无需加 `instruction` 前缀（v1.5 简化） |
| **HF 模型卡** | `https://huggingface.co/BAAI/bge-base-zh-v1.5` |

**为什么选 BGE？**
- 中文语义理解优于 multilingual-e5 和 text2vec
- MTEB 中文榜单 Top 级别
- `sentence-transformers` 直接兼容，API 简洁
- 768 维，存储和计算开销可控

### 1.2 框架：sentence-transformers

```python
from sentence_transformers import SentenceTransformer

# 一行加载
model = SentenceTransformer("BAAI/bge-base-zh-v1.5", device="cpu")

# 一行编码
embeddings = model.encode(texts, batch_size=32, normalize_embeddings=True)
```

`sentence-transformers` 内部封装了：
1. HuggingFace `transformers` — 加载 BERT 权重
2. `torch` — 前向推理
3. Mean Pooling — 将 token embeddings 聚合为句向量
4. L2 Normalization — 归一化到单位球面

### 1.3 计算：NumPy

查询阶段完全脱离 PyTorch：
```python
scores = np.dot(emb_matrix, q_emb)   # (N, 768) @ (768,) → (N,)
top_k = np.argsort(scores)[-k:][::-1]
```
PyTorch 只在索引进场（`model.encode()`）时使用，查询阶段纯 NumPy。

---

## 2. 索引构建

### 2.1 入口

```bash
# 电视剧
python3 build_index.py --project 都挺好

# 口播
python3 build_index.py --project 杨老师教育
```

`build_index.py` 通过项目配置文件的 `type` 字段自动分发：
- `type: "drama"` → `build_drama_index()`
- `type: "interview"` → `build_interview_index()`

### 2.2 电视剧索引构建 (`build_drama_index`)

**数据源：** VLM 画面分析 + ASR 转写 + VLM 结构化字幕

```
sources_clean/  (优先, clean_data.py 产出)
  └── ep1/
      ├── vlm_merged.json     ← VLM 场景描述 (合并清洗后)
      │   [{
      │     "scene_id": 0,
      │     "start": 0.0, "end": 15.2,
      │     "description": "苏明玉站在办公室窗前...",
      │     "tags": ["indoor", "dialogue"],
      │     "subtitles": ["你说的对", "我知道该怎么做了"]
      │   }, ...]
      └── asr_result.json     ← ASR 转写
          [{"start": 0.5, "end": 3.2, "text": "明玉啊你听我说"}, ...]

sources/  (fallback, analyze_episodes.py 原始产出)
```

**构建过程：**

```python
def build_drama_index(project_dir, drama_name):
    # Step 1: 加载模型
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)

    # Step 2: 遍历每集，收集文本
    texts, metas = [], []
    for ep in episodes:
        # 2a: VLM 场景描述 (每个 scene → 1 条索引)
        for scene in vlm_merged:
            if "skip_opening" in scene.tags:  # 跳过片头
                continue
            if len(scene.description) > 10:
                texts.append(scene.description)
                metas.append({
                    "type": "vlm",      # 索引类型标记
                    "ep": ep,
                    "scene_id": scene.scene_id,
                    "start": scene.start,
                    "end": scene.end,
                    "text": scene.description[:200]
                })

        # 2b: VLM 结构化字幕 (每个字幕句 → 1 条索引)
        for scene in vlm_merged:
            for sub in scene.subtitles:
                if len(sub) >= 3:
                    texts.append(sub)
                    metas.append({
                        "type": "sub",  # 字幕类型
                        "ep": ep,
                        "scene_id": scene.scene_id,
                        "start": scene.start,
                        "end": scene.end,
                        "text": sub[:200]
                    })

        # 2c: ASR 转写 (每个片段 → 1 条索引)
        for seg in asr_result:
            if len(seg.text) > 8:
                texts.append(seg.text)
                metas.append({
                    "type": "asr",      # ASR 类型
                    "ep": ep,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text[:200]
                })

    # Step 3: 批量编码
    embeddings = model.encode(texts,
        show_progress_bar=True,
        batch_size=32,              # 每次前向 32 句
        normalize_embeddings=True   # L2 归一化
    )

    # Step 4: 双格式保存
    save_index(project_dir, embeddings, metas, texts)
```

**索引条目构成：** 同一集的三类文本（VLM 描述 + 字幕 + ASR）全部进入同一个向量空间，查询时按相似度竞争排序，不再区分来源。

### 2.3 口播索引构建 (`build_interview_index`)

**数据源：** `classified_enhanced.json`（经 LLM 清洗 + 分类 + 说话人标注）

```json
[{
  "start_sec": 2.5,
  "text": "我觉得新东方最核心的就是那种",
  "cleaned_text": "新东方最核心的是对学生的那种关爱",
  "speaker": "guest",
  "layer": "content",
  "importance": 4
}, ...]
```

**与电视剧的 3 个关键区别：**

#### 区别 1：只索引入 guest + content/guide

```python
# 过滤条件
indexable = [
    s for s in data
    if s.get('speaker') == 'guest'          # 只要被采访者
    and s.get('layer') in ('content', 'guide')  # 只要内容层/引导层
]
# 排除: host 主持人说话, meta 元评论, filler 废料
```

#### 区别 2：说话人边界断句

```python
# speaker 从 guest 变成 host 时 → 断开，开始新的语义单元
if last_speaker and speaker != last_speaker:
    merged = " ".join(chunk_texts)
    texts.append(merged)

# 时间窗口超过 15 秒 或 句子数超过 5 句 → 断开
if seg_end - chunk_start >= 15 or len(chunk_texts) >= 5:
    merged = " ".join(chunk_texts)
    texts.append(merged)
```

#### 区别 3：优先使用 cleaned_text

```python
cleaned = seg.get('cleaned_text', seg.get('text', ''))
# cleaned_text 经过 DeepSeek 清洗: 去除口语废词, 语法修正, 内容提纯
```

**构建过程：**

```python
def build_interview_index(project_dir):
    # Step 1: 加载 enhanced 数据
    data = json.load(open("classified_enhanced.json"))
    indexable = [s for s in data
                 if s.speaker == 'guest'
                 and s.layer in ('content', 'guide')]

    # Step 2: 按时间排序 + 说话人边界合并
    texts, metas = [], []
    for seg in sorted(indexable, key=lambda s: s.start_sec):
        # 判定是否需要断开
        if speaker_changed or duration >= 15s or sentence_count >= 5:
            merged = " ".join(chunk_texts)
            texts.append(merged)
            metas.append({
                "source": "学习新东方",
                "start": chunk_start,
                "end": seg_end,
                "text": merged,              # cleaned_text 合并
                "original_text": merged_orig  # 原始 ASR 文本保留
            })

    # Step 3: 编码
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)
    embeddings = model.encode(texts, batch_size=64, normalize_embeddings=True)

    # Step 4: 保存
    save_index(project_dir, embeddings, metas, texts)
```

### 2.4 保存：双格式策略 (`save_index`)

```python
def save_index(project_dir, embeddings, metas, texts):
    # 格式 1: Pickle（遗留兼容，一次性加载）
    data = {
        "embeddings": embeddings.astype(np.float32),
        "metas": metas,
        "texts": texts
    }
    with open("semantic_index.pkl", "wb") as f:
        pickle.dump(data, f)

    # 格式 2: NPY + JSON（推荐，mmap 零拷贝）
    np.save("semantic_embeddings.npy", embeddings.astype(np.float32))
    with open("semantic_metas.json", "w") as f:
        json.dump(metas, f, ensure_ascii=False, indent=2)
```

| 格式 | 文件 | 加载方式 | 内存占用 |
|------|------|----------|----------|
| Pickle | `semantic_index.pkl` | `pickle.load()` 整体读入 | 全部复制到内存 |
| **mmap** | `semantic_embeddings.npy` | `np.load(mmap_mode='r')` | 操作系统页缓存，零拷贝 |

**为什么需要两种格式？**
- Pickle 是历史遗留，兼容老版本
- NPY mmap 是推荐方式：操作系统按需换页，启动快，多进程共享物理内存

---

## 3. 索引加载

`server.py` 启动时加载索引到全局变量：

```python
# 全局变量
semantic_emb = None    # (N, 768) float32 矩阵
semantic_metas = None  # [{type, ep, start, end, text, ...}, ...]

# 加载逻辑 (按项目类型)
if _project_type == "drama":
    if INDEX_NPY.exists() and INDEX_META.exists():
        # 优先 mmap
        semantic_emb = np.load("semantic_embeddings.npy", mmap_mode='r')
        semantic_metas = json.load(open("semantic_metas.json"))
        # 输出: [search] 语义索引 (mmap): 8523 条, 768维
    elif INDEX_FILE.exists():
        # fallback pickle
        old = pickle.load(open("semantic_index.pkl", "rb"))
        semantic_emb = old["embeddings"]
        semantic_metas = old["metas"]

elif _project_type == "interview":
    if INDEX_NPY.exists() and INDEX_META.exists():
        semantic_emb = np.load("semantic_embeddings.npy", mmap_mode='r')
        semantic_metas = json.load(open("semantic_metas.json"))
        # 输出: [search] 口播语义索引: 486 条, 768维
```

**内存估算：**

```
电视剧 (46集):  8500条 × 768维 × 4字节(float32) ≈ 26 MB
口播 (1个素材):  500条 × 768维 × 4字节(float32) ≈ 1.5 MB
```

### mmap 工作原理

```
┌─────────────────────────────────────────────────────┐
│  进程虚拟地址空间                                     │
│  ┌──────────────────────────┐                        │
│  │  semantic_emb (mmap)      │  ← 直接映射文件页      │
│  │  np.dot() 随机访问        │                        │
│  └──────────┬───────────────┘                        │
│             │ page fault                              │
│             ▼                                         │
│  ┌──────────────────────────┐                        │
│  │  操作系统页缓存 (Page Cache)│                      │
│  │  按需加载，LRU 淘汰        │                       │
│  └──────────┬───────────────┘                        │
│             │                                         │
│             ▼                                         │
│  semantic_embeddings.npy  (磁盘文件)                   │
└─────────────────────────────────────────────────────┘

优势:
  - 启动瞬间完成 (不解析文件, 只建立映射)
  - 多进程共享同一份物理内存
  - 操作系统自动管理换页, 无需手动控制
```

---

## 4. 查询检索

### 4.1 编码器（懒加载单例）

```python
_enc_model = None

def _encode(text):
    global _enc_model
    if _enc_model is None:
        from sentence_transformers import SentenceTransformer
        _enc_model = SentenceTransformer("BAAI/bge-base-zh-v1.5")
        # 首次调用时加载模型 (~2s)
    return _enc_model.encode([text], normalize_embeddings=True)[0]
    # 返回 (768,) float32 归一化向量
```

**设计要点：**
- 懒加载：第一次搜索时才加载模型，不阻塞启动
- 单例：整个进程生命周期只加载一次
- Query 也是 L2 归一化：`dot(q_emb, doc_emb)` 等价于余弦相似度

### 4.2 语义搜索（核心算法）

```python
def _semantic_search(self, query, limit=10):
    if semantic_emb is None:
        return []

    # ── Step 1: 查询编码 ──
    q_emb = _encode(query)              # (768,) float32

    # ── Step 2: 矩阵乘法（余弦相似度）──
    scores = np.dot(semantic_emb, q_emb)  # (N, 768) @ (768,) → (N,)
    # 等价于: cos(query, doc_i)  for all i

    # ── Step 3: Top-K ──
    top = np.argsort(scores)[-30:][::-1]  # 取最高 30 个索引, 降序

    # ── Step 4: 阈值过滤 + 去重 ──
    results = {}
    for i in top:
        # 口播: 阈值 0.30, 电视剧: 阈值 0.35
        if scores[i] <= threshold:
            continue

        m = metas[i]

        # 去重 key: 同一时间位置只保留最高分
        key = f"{m['ep']}_{m['start']:.0f}"  # 电视剧
        # key = f"{m['source']}_{m['start']:.0f}"  # 口播

        if key not in results or score > results[key]["score"]:
            results[key] = {
                "start": m["start"],
                "end": m["end"],
                "description": m["text"][:200],
                "score": round(float(scores[i]) * 100, 1),   # 0-100
                ...
            }

    return sorted(results.values(), key=lambda x: -x["score"])[:limit]
```

### 4.3 分数含义

```
scores[i] ∈ [-1, 1]    (L2 归一化后, dot 值即余弦值)
score_pct = scores[i] * 100   →  前端显示 0-100

阈值:
  电视剧: scores[i] > 0.35  (即 > 35%)  — 较宽松, VLM 描述文本长
  口播:   scores[i] > 0.30  (即 > 30%)  — 更严格, ASR 口语短句
```

### 4.4 混合搜索（语义 + 关键词）

```python
def _hybrid_search(self, query, limit=10):
    # 1. 语义搜索
    semantic_results = self._semantic_search(query, 30)

    # 2. 关键词搜索（ngram + jaccard）
    keyword_results = self._keyword_search(query, 20)

    # 3. 加权合并
    combined = {}
    for r in semantic_results:
        combined[r.key] = r.score * 0.7    # 语义权重 70%
    for r in keyword_results:
        if r.key in combined:
            combined[r.key] += r.score * 0.3  # 关键词权重 30%
        else:
            combined[r.key] = r.score * 0.3

    return sorted(combined, key=lambda x: -x[1])[:limit]
```

### 4.5 API 调用方式

```
GET /search?q=苏明玉被开除&mode=semantic   → 纯语义
GET /search?q=苏明玉被开除&mode=keyword    → 纯关键词
GET /search?q=苏明玉被开除&mode=hybrid     → 混合 (默认)
GET /search?q=苏明玉被开除                 → 混合 (默认 mode)
```

---

## 5. 电视剧 vs 口播 — 双模式对比

| 维度 | 电视剧 (drama) | 口播 (interview) |
|------|---------------|------------------|
| **数据源** | VLM 场景描述 + ASR 转写 + 字幕 | cleaned_text (LLM 清洗后) |
| **索引类型** | 3 种混合 (vlm/sub/asr) | 1 种 (guest content) |
| **过滤** | 跳过片头 (`skip_opening`) | 跳过 host/filler/meta |
| **合并策略** | 不合并（每个片段独立） | 说话人边界合并（连续 guest 合并为一段） |
| **文本来源** | 原始 ASR + VLM 原始描述 | `cleaned_text` 优先, fallback `text` |
| **编码批大小** | batch_size=32 | batch_size=64 |
| **查询阈值** | > 0.35 | > 0.30 |
| **去重 Key** | `ep_start` | `source_start` |
| **索引规模** | ~8500 条 | ~500 条 |
| **embeddings 文件** | `都挺好/semantic_embeddings.npy` | `杨老师教育/semantic_embeddings.npy` |

### 为什么口播要"说话人边界合并"？

```
原始 ASR 片段 (未合并):
  [guest] "我觉得"                    ← 3字, 无效语义
  [guest] "新东方最核心的"             ← 8字, 半句话
  [guest] "就是对学生的那种关爱"       ← 10字, 半句话

合并后 (同一 speaker 连续 → 合并):
  [guest] "新东方最核心的是对学生的那种关爱"  ← 完整句子, 语义完整

效果: BGE 对完整句子的 embedding 质量远高于碎片短句
```

---

## 6. 存储格式与性能

### 6.1 文件清单

```
项目目录/
├── semantic_embeddings.npy   ← 向量矩阵 (N × 768 × 4字节)
├── semantic_metas.json       ← 元数据 (start, end, text, type, ep...)
├── semantic_index.pkl        ← 遗留 pickle (embeddings + metas + texts 打包)
```

### 6.2 规模与性能 (实测参考)

| 项目 | 索引条数 | embeddings | metas | 搜索耗时 |
|------|----------|------------|-------|----------|
| 都挺好 (46集) | ~8500 | ~26 MB | ~3 MB | <5ms |
| 杨老师教育 | ~500 | ~1.5 MB | ~0.3 MB | <1ms |

```
查询耗时拆解:
  _encode()          ~50ms  (BERT 前向, 首次 ~2s)
  np.dot()           ~1ms   (矩阵乘法)
  argsort + 过滤     <1ms
  ────────────────────────
  总计               ~52ms  (首次 ~2s, 后续 ~50ms)

编码优化:
  - 首次 encode() 触发 PyTorch 模型加载 (~2s)
  - 后续调用直接推理, 单句 ~50ms (CPU)
  - 可预热 _encode("预热") 避免首次延迟
```

### 6.3 mmap vs pickle 性能对比

```
                pickle 加载        mmap 加载
启动耗时:       ~200ms (解析)      ~1ms (映射)
内存占用:       全部占用 (~30MB)   按需加载
多进程共享:     ❌ 各自复制         ✅ 共享物理页
首次查询:       即时               可能触发 page fault (~10ms)
```

---

## 7. 数据流全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                        索引构建 (build_index.py)                   │
│                                                                    │
│  电视剧:                                                           │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                       │
│  │ VLM 场景  │   │ VLM 字幕  │   │ ASR 转写  │                      │
│  │ description│  │ subtitles │   │ text     │                      │
│  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘                      │
│        │               │               │                            │
│        └───────────────┼───────────────┘                            │
│                        │ texts[] (去片头, 长度过滤)                   │
│                        ▼                                            │
│  口播:                                                ┌──────────┐ │
│  ┌────────────────────┐                               │  BGE     │ │
│  │ classified_enhanced │  → guest-only                │  model   │ │
│  │ (LLM 清洗+分类)     │  → speaker 边界合并           │  encode  │ │
│  └────────────────────┘  → cleaned_text 优先          └────┬─────┘ │
│                        │                                    │        │
│                        ▼                                    │        │
│              texts[] + metas[]                              │        │
│                        │                                    │        │
│                        └────────────────────────────────────┘        │
│                                           │                         │
│                                           ▼                         │
│                              embeddings (N × 768)                    │
│                                           │                         │
│                          ┌────────────────┼────────────────┐        │
│                          ▼                                 ▼        │
│              semantic_embeddings.npy          semantic_metas.json   │
│              (mmap 零拷贝)                     (元数据)              │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                        查询检索 (server.py)                        │
│                                                                    │
│  GET /search?q=苏明玉被开除                                        │
│       │                                                            │
│       ▼                                                            │
│  ┌──────────────────────┐                                         │
│  │ _encode(query)        │  ← BGE 模型 (懒加载单例)                 │
│  │ → q_emb (768,)        │                                         │
│  └──────────┬───────────┘                                         │
│             │                                                      │
│             ▼                                                      │
│  ┌──────────────────────┐                                         │
│  │ np.dot(emb, q_emb)    │  ← 矩阵乘法, N 次余弦相似度               │
│  │ → scores (N,)         │                                         │
│  └──────────┬───────────┘                                         │
│             │                                                      │
│             ▼                                                      │
│  ┌──────────────────────┐                                         │
│  │ np.argsort()[-30:]    │  ← Top-30                              │
│  │ 阈值过滤 (0.30/0.35)  │                                         │
│  │ 去重 (同一位置取最高分)│                                         │
│  └──────────┬───────────┘                                         │
│             │                                                      │
│             ▼                                                      │
│  ┌──────────────────────────────────────────┐                     │
│  │ 混合搜索 (可选)                            │                     │
│  │ semantics * 0.7 + keyword * 0.3           │                     │
│  └──────────┬───────────────────────────────┘                     │
│             │                                                      │
│             ▼                                                      │
│  JSON Response:                                                    │
│  [{start, end, description, asr, score, source}, ...]             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 附录：关键代码位置

| 功能 | 文件 | 行号 |
|------|------|------|
| 模型加载 + 编码入口 | `build_index.py` | 23-25, 116, 225 |
| 电视剧文本收集 (VLM+ASR+SUB) | `build_index.py` | 126-154 |
| 口播文本收集 (guest-only + 边界合并) | `build_index.py` | 158-229 |
| 双格式保存 | `build_index.py` | 232-245 |
| 索引加载 (mmap/pickle fallback) | `server.py` | 347-403 |
| 编码器单例 | `server.py` | 2632-2639 |
| 语义搜索核心算法 | `server.py` | 870-911 |
| 混合搜索 | `server.py` | 913-950 (keyword) + 调用处 |
| Agent 调用搜索 | `server.py` | 20-41 (注入 `set_search_fn`) |
| 预热逻辑 | `server.py` | 44-59 |

---

> 文档版本: v1.0 | 生成日期: 2026-08-04
