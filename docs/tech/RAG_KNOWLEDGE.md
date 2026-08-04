# RAG 知识体系 — 概念、框架与学习路径

> 从 VibeCut 出发，理解检索增强生成的全貌

---

## 目录

1. [RAG 到底是什么](#1-rag-到底是什么)
2. [RAG 的技术分层](#2-rag-的技术分层)
3. [VibeCut 就是 RAG — 只是你没用这个词](#3-vibecut-就是-rag--只是你没用这个词)
4. [RAG 框架生态全景](#4-rag-框架生态全景)
5. [LangChain 的 RAG 定位](#5-langchain-的-rag-定位)
6. [LlamaIndex — RAG 专用框架](#6-llamaindex--rag-专用框架)
7. [其他值得关注的 RAG 框架](#7-其他值得关注的-rag-框架)
8. [VibeCut 的 RAG 选型建议](#8-vibecut-的-rag-选型建议)
9. [学习路线](#9-学习路线)

---

## 1. RAG 到底是什么

RAG (Retrieval-Augmented Generation) 的本质非常简单：

```
用户提问 → 从"知识库"中检索相关信息 → 把检索结果拼入 prompt → LLM 生成回答

三个步骤:
  1. Retrieval (检索):    从你的数据中找到相关内容
  2. Augmented  (增强):   把检索结果注入 LLM 的 prompt
  3. Generation (生成):    LLM 基于增强后的 prompt 生成输出
```

**但"知识库"这个词已经不够用了。** RAG 可以检索的内容远不止文档：

```
RAG 的多样性 — 你检索的可以是任何东西:

  ┌─────────────────────────────────────────────────────┐
  │ 传统 RAG:        "聊文档"                            │
  │  PDF/DOCX/TXT → Chunk → Embed → 检索 → LLM 回答    │
  │                                                     │
  │ 代码 RAG:         "聊代码库"                          │
  │  GitHub repo → AST 解析 → Embed → 检索 → 生成代码     │
  │                                                     │
  │ 多媒体 RAG:       "聊视频/音频"                        │
  │  视频 → ASR+VLM → 时间片段 → Embed → 检索 → 脚本生成   │
  │                                          ↑           │
  │                                   VibeCut 就是这个!   │
  │                                                     │
  │ Graph RAG:        "聊知识图谱"                        │
  │  实体+关系 → 图索引 → 子图检索 → LLM 推理             │
  │                                                     │
  │ Agentic RAG:      "AI 主动检索"                       │
  │  Agent 决定搜什么、搜几次、怎么筛选 → LLM 综合         │
  └─────────────────────────────────────────────────────┘
```

**所以 RAG 的核心不是 "文档问答"，而是 "用检索弥补 LLM 的知识盲区"。** 只要你的应用模式是 "检索 + 生成"，你就是 RAG。

---

## 2. RAG 的技术分层

把 RAG 拆成技术层次，才能理解哪个框架解决了哪一层：

```
┌────────────────────────────────────────────────────────────┐
│  Layer 5: 应用层 — 对话管理 / 会话记忆 / 用户界面            │
│  LangChain ConversationBufferMemory / 自建                    │
├────────────────────────────────────────────────────────────┤
│  Layer 4: 生成层 — Prompt 组装 / LLM 调用 / 流式输出         │
│  LangChain prompt template / LiteLLM / 直接调 API            │
├────────────────────────────────────────────────────────────┤
│  Layer 3: 检索层 — 向量搜索 / 关键词搜索 / 混合搜索 / 重排序   │
│  BGE + numpy / Chroma / Qdrant / LangChain Retriever        │
├────────────────────────────────────────────────────────────┤
│  Layer 2: 索引层 — Chunking / Embedding / 元数据抽取          │
│  LlamaIndex IngestionPipeline / LangChain TextSplitter        │
├────────────────────────────────────────────────────────────┤
│  Layer 1: 数据层 — 文档解析 / 格式转换 / 数据清洗              │
│  LlamaIndex Readers / LangChain Document Loaders / 自建      │
└────────────────────────────────────────────────────────────┘
```

**关键认知：每个 RAG 框架都有自己的主力层，没有全能的。**

| 框架 | 主力层 | 定位 |
|------|--------|------|
| **LlamaIndex** | Layer 1 + 2 | 数据摄入和索引构建最强 |
| **LangChain** | Layer 3 + 4 | 检索和生成编排最通用 |
| **Chroma / Qdrant** | Layer 3 | 纯向量存储和检索 |
| **LangGraph** | Layer 4 + 5 | Agent 级编排，超越简单 RAG |
| **Dify / RAGFlow** | Layer 1-5 | 全栈产品（低代码拖拽） |

---

## 3. VibeCut 就是 RAG — 只是你没用这个词

把 VibeCut 的核心管线映射到 RAG 五层模型：

```
VibeCut 当前实现                           RAG 标准概念

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Layer 1: 数据层
  analyze_episodes.py                     Document Loading
  ├── 音频提取 → ASR 转写                   ├── PDFReader (文档解析)
  └── 视频关键帧 → VLM 分析                 └── SimpleDirectoryReader (批量加载)
  
  classify_transcript.py                  Data Cleaning
  ├── LLM 四层分类 (content/meta/...)       └── Metadata Extraction
  └── 说话人识别                             

Layer 2: 索引层
  build_index.py                          IngestionPipeline
  ├── 文本收集 (VLM描述 + ASR + 字幕)       ├── TextSplitter (Chunking)
  │   → 说话人边界合并 (口播)              │   → 固定窗口 / 语义分割 / 递归分割
  │   → 长度过滤 (>10字)                  │   → overlap 控制
  └── BGE encode → normalize              └── Embedding Model → Vector Store
      → 768维向量

Layer 3: 检索层
  server.py _semantic_search()            Retriever
  ├── BGE encode(query)                    ├── Vector Search (余弦相似度)
  ├── np.dot → Top-K                       ├── Keyword Search (BM25)
  ├── 阈值过滤 (0.30/0.35)                 ├── Hybrid Search (向量 + 关键词加权)
  ├── 去重 (同位置保留最高分)               ├── Reranking (Cross-encoder 重排序)
  └── n-gram 关键词加权                     └── Metadata Filtering (WHERE speaker='guest')

Layer 4: 生成层
  script_agents.py                        Generation / Synthesis
  ├── planning_agent: 主题→叙事结构        ├── Prompt Template
  ├── writer_agent:  段定义+BGE搜→选句     ├── RAG Prompt (context + query)
  ├── editor_agent:  压缩 + 时间多样性      └── Response Synthesis Mode:
  └── reviewer_agent: 7维评分                 ├── Compact (压缩后一次生成)
                                               ├── Refine (逐段精炼)
                                               └── Tree Summarize (分层汇总)

Layer 5: 应用层
  VibeEdit / PlanningDesk                  Chat Interface
  ├── SSE 流式展示 Agent 进度              ├── 多轮对话 (ChatPanel + _chat_intent)
  └── 精切 sub_clips 预览                  │   ✅ 全文消息历史传递
                                           │   ✅ LLM 累积约束条件
                                           │   ⚠️ 浅层: query 精炼模式,无搜索策略反思
                                           └── Conversational Memory (未持久化)
```

**发现了什么？** VibeCut 实现了 RAG 的每一层，而且是**面向多模态视频素材的领域特化 RAG**。

但比较 "标准 RAG vs VibeCut RAG" 会发现：

| 维度 | 标准文档 RAG | VibeCut RAG |
|------|-------------|-------------|
| 文档格式 | PDF/DOCX/TXT | 视频 (通过 ASR/VLM 转为文本) |
| Chunking | 固定 token 窗口 / 递归分割 | 说话人边界 / 场景边界 / 时间窗口 |
| 元数据 | 文件名、页码、创建时间 | 时间戳、说话人、layer、importance |
| 检索粒度 | 文本块 | 时间片段 (start_sec → end_sec) |
| 生成目标 | 回答问题 | 生成剪辑脚本 (段落 + 时间位置) |
| 相关性 = | 语义相似 | 语义相似 + 时间多样性 + 叙事角色 |

**这就是为什么通用 RAG 框架不能直接套用到 VibeCut — 它的领域特性（时间轴、说话人、叙事结构）太强了。**

---

## 4. RAG 框架生态全景

```
                          RAG 框架生态地图 (2025-2026)

  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  开发框架 (Library)                产品平台 (Platform)            │
  │  ┌────────────┐                    ┌──────────────┐             │
  │  │ LangChain   │ ← 通用 LLM 框架   │  Dify         │ ← 低代码    │
  │  │ (RAG 模块)  │    内置 RAG 组件   │  RAGFlow      │   拖拽建    │
  │  └────────────┘                    │  Coze         │   知识库    │
  │  ┌────────────┐                    └──────────────┘             │
  │  │ LlamaIndex  │ ← RAG 专用框架                                 │
  │  │             │    数据摄入最强   ┌──────────────┐             │
  │  └────────────┘                    │  LangFuse     │ ← 可观测性  │
  │  ┌────────────┐                    │  (评估+追踪)  │             │
  │  │ Haystack    │ ← 企业级 RAG      │  RAGAS        │ ← RAG 评估  │
  │  │ (Deepset)   │    Pipeline 抽象  └──────────────┘             │
  │  └────────────┘                                                  │
  │  ┌────────────┐    ┌─────────────────────────┐                  │
  │  │ DSPy        │ ← 声明式 LLM 编程             │                  │
  │  │             │    "compile" 而非 "prompt"    │                  │
  │  └────────────┘    └─────────────────────────┘                  │
  │                                                                  │
  │  向量数据库 (Infrastructure)                                      │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐         │
  │  │ Chroma    │ │ Qdrant   │ │ Milvus   │ │ LanceDB    │         │
  │  │ (嵌入模式)│ │ (高性能) │ │ (分布式) │ │ (列式存储) │         │
  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘         │
  │                                                                  │
  └─────────────────────────────────────────────────────────────────┘
```

先澄清一个常见误解：**LangChain 不是 "RAG 框架"，它是一个 "LLM 应用框架"，RAG 只是它的一个模块。** LlamaIndex 才是 RAG 专用框架。

---

## 5. LangChain 的 RAG 定位

### 5.1 LangChain 的 RAG 模块做了什么

```python
# LangChain 的 RAG 标准写法
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# Step 1: 加载文档
loader = PyPDFLoader("knowledge.pdf")
docs = loader.load()

# Step 2: 切分
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
chunks = splitter.split_documents(docs)

# Step 3: Embed + 存向量数据库
vectorstore = Chroma.from_documents(chunks, OpenAIEmbeddings())

# Step 4: 构建检索链
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

prompt = ChatPromptTemplate.from_messages([
    ("system", "根据以下上下文回答问题: {context}"),
    ("user", "{input}")
])

qa_chain = create_stuff_documents_chain(llm, prompt)      # ← 生成
rag_chain = create_retrieval_chain(retriever, qa_chain)   # ← 检索+生成

# Step 5: 使用
result = rag_chain.invoke({"input": "VibeCut 用了什么模型？"})
```

**这个流程的每一环都设计为可替换的抽象：**
- `DocumentLoader` → 可以换 PyPDFLoader / CSVLoader / WebBaseLoader
- `TextSplitter` → 可以换 Character / Recursive / Semantic / Markdown
- `VectorStore` → 可以换 Chroma / Qdrant / FAISS / Pinecone
- `Retriever` → 可以换 Vector / BM25 / Ensemble / Multi-Query
- `CombineDocumentsChain` → 可以换 stuff / refine / map_reduce / map_rerank

### 5.2 这套抽象对 VibeCut 的价值

| LangChain RAG 组件 | VibeCut 当前实现 | 替换价值 |
|-------------------|-----------------|---------|
| `DocumentLoader` | `json.load()` 手动读取 | **低** — VibeCut 的数据源是 JSON，langchain 的 PDF/CSV 加载器用不上 |
| `TextSplitter` | 说话人边界 + 时间窗口 | **低** — VibeCut 的分割逻辑是领域特化的，通用 splitter 不适用 |
| `VectorStore` | NumPy mmap + `np.dot` | **中** — 规模扩大后有用，但目前 8500 条不需要 |
| `Retriever` | `_semantic_search()` 自研 | **中** — LangChain 的 Retriever 抽象能统一搜索接口 |
| `CombineDocumentsChain` | Agent 手动拼 prompt | **高** — stuff/refine/map_reduce 模式值得学习 |
| `ConversationalRetrievalChain` | 无对话记忆 | **高** — 如果需要多轮对话式剪辑 |

**结论：LangChain 的 RAG 模块对标准文档问答场景价值极高，但对 VibeCut 这种领域特化 RAG，大部分抽象是多余的。** 它的价值主要在 Layer 4（生成层的 stuff/refine 模式）和 Layer 5（对话管理），而不是 Layer 1-3。

---

## 6. LlamaIndex — RAG 专用框架

### 6.1 LlamaIndex vs LangChain 的差异

```
LangChain 做 RAG:                          LlamaIndex 做 RAG:

"创建一个带 RAG 能力的 LLM 应用"           "构建一个数据密集型 AI 系统"

从 LLM 侧出发 → 组合检索模块            从数据侧出发 → 构建索引和查询引擎
Chain + Retriever + VectorStore          Ingestion Pipeline + Query Pipeline

通用 LLM 应用框架                         专为 RAG 设计
文档加载器是插件                           文档加载器是核心
1 种检索模式                              10+ 种检索模式
```

### 6.2 LlamaIndex 的核心概念

```python
# LlamaIndex 的思维模型
from llama_index.core import (
    VectorStoreIndex,                    # 索引
    SimpleDirectoryReader,               # 读取
    Settings,                            # 全局配置
    StorageContext,                       # 持久化
)
from llama_index.core.node_parser import (
    SentenceSplitter,                    # 语义切分
    SemanticSplitterNodeParser,          # 基于 Embedding 的切分
)
from llama_index.core.retrievers import (
    VectorIndexRetriever,                # 向量检索
    BM25Retriever,                       # 关键词检索
)
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import (
    SentenceTransformerRerank,           # 重排序 (Cross-encoder)
    SimilarityPostprocessor,             # 相似度阈值
)

# ── 数据加载 ──
documents = SimpleDirectoryReader(
    "./素材/",
    required_exts=[".json", ".txt"],
    recursive=True
).load_data()

# ── 索引构建 (可组合的 Pipeline) ──
from llama_index.core.ingestion import IngestionPipeline

pipeline = IngestionPipeline(
    transformations=[
        SentenceSplitter(chunk_size=256, chunk_overlap=20),
        HuggingFaceEmbedding(model_name="BAAI/bge-base-zh-v1.5"),
    ]
)
nodes = pipeline.run(documents=documents)

# ── 存入索引 ──
index = VectorStoreIndex(nodes)
index.storage_context.persist("./llama_index_cache")

# ── 查询引擎 ──
query_engine = RetrieverQueryEngine.from_args(
    retriever=VectorIndexRetriever(index=index, similarity_top_k=10),
    node_postprocessors=[
        SimilarityPostprocessor(similarity_cutoff=0.35),
        SentenceTransformerRerank(model="BAAI/bge-reranker-v2-m3", top_n=5),  # ← 重排序!
    ]
)

# ── 查询 ──
response = query_engine.query("新东方的教育理念")
print(response.source_nodes)  # 每条结果的来源 + 分数
```

### 6.3 LlamaIndex 独有的 RAG 能力

这些是 LangChain 没有或做得不够好的，也是学习 RAG 的关键知识点：

#### (1) IngestionPipeline — 声明式数据摄入

```python
# 声明式定义处理步骤，自动并行执行
pipeline = IngestionPipeline(
    transformations=[
        TextCleaner(),           # 去噪
        SentenceSplitter(),      # 切分
        MetadataExtractor(),     # 抽取元数据
        embed_model,             # 向量化
    ],
    cache=IngestionCache(),      # 增量更新 (已处理的 doc 自动跳过)
)
```

对应 VibeCut 的：`classify_transcript.py → clean_interview_data.py → build_index.py`

#### (2) 检索模式 — 远超 "向量搜索 Top-K"

```
LlamaIndex 检索模式一览:

  Vector Search:        向量余弦相似度 (VibeCut 当前)
  Keyword Search:       BM25 全文检索
  Hybrid Search:        向量 + BM25 加权融合
  Recursive Retrieval:  先查摘要/父节点，再深入子节点
  Auto-Merging:         检索时动态合并相邻 chunk
  Small-to-Big:         检索小粒度，生成时扩展到大粒度上下文
  Multi-Step:           多步检索 — 第一次检索 → LLM 判断 → 第二次精确检索
  Router:               LLM 选择检索策略 (该搜哪个索引、哪种模式)
  Knowledge Graph:      实体关系图增强检索 (Graph RAG)
```

VibeCut 目前只有 Vector + Keyword Hybrid。这些模式是学习 RAG 深度的核心素材。

#### (3) 结构化数据提取 — 不只要文本，还要结构化答案

```python
# 从素材中提取结构化信息
from llama_index.core.extractors import (
    TitleExtractor,
    KeywordExtractor,
    QuestionsAnsweredExtractor,
    SummaryExtractor,
)

# 索引时自动抽取元数据
index = VectorStoreIndex(
    nodes,
    transformations=[
        embed_model,
        TitleExtractor(nodes=3),           # 自动生成标题
        QuestionsAnsweredExtractor(nodes=5), # 自动生成 "这段能回答什么问题"
    ]
)

# 之后查询时，可以根据元数据预过滤
retriever = VectorIndexRetriever(
    index=index,
    filters=MetadataFilters(
        filters=[MetadataFilter(key="speaker", value="guest")]
    )  # 只检索 guest 发言
)
```

这对应 VibeCut 的 `layer` 和 `speaker` 过滤，但 LlamaIndex 让它更结构化。

---

## 7. 其他值得关注的 RAG 框架

| 框架 | 一句话 | 适合什么场景 |
|------|--------|-------------|
| **Haystack** (deepset) | 企业级 RAG Pipeline，组件化 → 可组合 → 可部署 | 需要生产级 REST API、需要 Pipeline 可视化的场景 |
| **DSPy** (Stanford) | "编译" prompt 而非手写 — 用优化器自动找最佳 prompt | 想理解 "prompt engineering 可以自动化" 这个概念 |
| **RAGFlow** | 中国团队，深度文档解析 (表格/图表/排版保留) | 复杂 PDF 场景 (但 VibeCut 不涉及) |
| **Dify** | 拖拽式 RAG 应用构建平台 | 非开发者使用 / 快速原型 |
| **FastGraphRAG** | 知识图谱 + RAG，自动从文档构建实体关系图 | 需要理解实体间关系的复杂问答 |
| **Crawl4AI** | 网页爬取 + AI 清洗 → RAG 数据源 | 需要爬取网页作为知识库 |

---

## 8. VibeCut 的 RAG 选型建议

回到 VibeCut 的实际情况，分层来看：

```
VibeCut RAG 各层的选型建议:

Layer 1: 数据解析 — 不需要框架
  数据源: JSON (ASR/VLM 结果), 格式固定
  → 不需要 PDF Loader、不需要 Doc Parser
  → 继续用 json.load() ✅

Layer 2: 索引构建 — 考虑 LlamaIndex
  当前: build_index.py 手动维护
  LlamaIndex 价值:
    ✅ IngestionPipeline (声明式, 可缓存增量)
    ✅ 多种 Chunking 策略 (学习价值)
    ✅ Metadata Extraction 自动化
    ❌ 但 VibeCut 的领域 Chunking 逻辑 (说话人边界/时间窗口)
       需要自定义, 框架抽象不增值

Layer 3: 检索 — 考虑 LlamaIndex Retriever
  当前: NumPy np.dot + argsort
  LlamaIndex 价值:
    ✅ 多检索模式 (Router / Recursive / Auto-Merging)
    ✅ 内置 Reranker (Cross-encoder 重排序)
    ✅ Metadata Filtering 声明式 API
    ⚠️ 但 VibeCut 的 8500 条数据, NumPy 够用且最快

Layer 4: 生成 — LangChain PromptTemplate + LangGraph
  当前: 硬编码 prompt 字符串 + 手动 Agent 链
  价值:
    ✅ ChatPromptTemplate (Prompt 管理)
    ✅ LangGraph (Agent 编排)
    ⚠️ LlamaIndex 的 ResponseSynthesizer 模式值得参考:
        - Compact: 压缩检索结果后一次生成 (VibeCut 当前的 editor_agent)
        - Refine: 逐段生成,每段引用新素材精炼 (适合精切场景)
        - Tree Summarize: 先分组摘要,再汇总 (适合长素材)

Layer 5: 对话 — 已有浅层实现,可深化
  ChatPanel 已实现多轮对话 (全文历史 + LLM 累积约束)
  但当前是 "query 精炼" 模式,距离 Agentic RAG 还有距离
```

### 核心结论

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  VibeCut RAG 选型:                                          │
│                                                            │
│  Layer 1-2: 不引入框架                                      │
│    理由: 数据格式固定,领域 Chunking 逻辑不可替代               │
│    但: 理解 LlamaIndex 的 IngestionPipeline 概念             │
│         可以帮助重构 build_index.py 的可维护性               │
│                                                            │
│  Layer 3: 暂时不引入 (numpy 够用)                            │
│    理由: 8500 条数据, NumPy < 5ms                            │
│    但: 如果数据量增长到 5万+, 引入 Chroma                     │
│         如果检索质量不够, 引入 Reranker (BGE-Reranker)       │
│                                                            │
│  Layer 4: 引入 LangChain PromptTemplate + LangGraph         │
│    理由: 硬编码 prompt 和手动 Agent 链是当前最大痛点          │
│                                                            │
│  Layer 5: 已有实现,可深化                                   │
│    当前: ChatPanel + _chat_intent 多轮 query 精炼            │
│    问题: LLM 只做 query 精炼,无搜索策略反思                    │
│    升级: LangGraph + Agentic RAG                             │
│    - 结构化状态: 已搜过的 query、已看过的结果、排除的方向       │
│    - 策略调整: "前两轮偏愤怒,换个情绪方向"                    │
│    - 主动性: "EP5 那个场景不错,要不要看看 EP8 的类似镜头?"     │
│                                                            │
│  从学习角度: 值得把 LlamaIndex 的 10+ 种检索模式              │
│    各写一个 demo 理解原理, 但不引入到 VibeCut 主流程          │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 9. 学习路线

从 "理解 RAG 全貌" 的学习视角，推荐的循序渐进路径：

```
Phase 1: 理解检索 — 你已经会了
│
├── VibeCut 的 BGE + NumPy 就是最纯粹的向量检索
├── 学点: 余弦相似度、L2 归一化、mmap 零拷贝
└── 对照: 看看 Chroma 源码的 HNSW 索引是怎么做的

Phase 2: 理解 Chunking — 核心认知跃迁
│
├── 写几个 demo 对比不同切分策略:
│   Fixed Window (500 tokens) vs Sentence Splitter vs Semantic Splitter
├── 观察同一 query 在不同切分策略下的检索结果差异
└── 理解: Chunking 是 RAG 质量的第一个决定因素

Phase 3: 理解检索策略 — 从 "最像的 N 个" 到 "最合适的 N 个"
│
├── 用 LlamaIndex 的 Retrieval Playground 对比:
│   Vector / BM25 / Hybrid / Recursive / Small-to-Big
├── 理解: 为什么有时候 "不太像但正好对" 比 "很像但用不上" 更重要
└── 学点: Reranker (Cross-encoder) 如何做二次精排

Phase 4: 理解生成策略 — 搜索结果如何喂给 LLM
│
├── stuff / refine / map_reduce / tree_summarize 四种模式
├── 动手: 同一批检索结果，分别用四种模式生成，对比效果
└── 理解: Token 窗口管理是 RAG 工程的核心约束

Phase 5: Agentic RAG — RAG 的下一步
│
├── Agent 自主决定: 搜什么、搜几次、怎么过滤、要不要重新搜
├── 用 LangGraph 实现: search → 判断 → search_again → generate
└── 理解: 从 "一次性检索" 到 "Agent 驱动多轮检索"
```

---

## 附录：快速对照 — 你要学什么就去碰什么

| 你想理解的概念 | 最好的学习材料 |
|---------------|---------------|
| Embedding 原理 | VibeCut 当前代码 (BGE + NumPy, 最干净) |
| Chunking 策略 | LlamaIndex Node Parser 文档 |
| 向量检索算法 | Chroma 源码 (HNSW 实现) |
| 检索模式多样性 | LlamaIndex Retriever Playground |
| RAG Prompt 工程 | LangChain `create_stuff_documents_chain` |
| Agentic RAG | LangGraph Multi-Step Agent example |
| RAG 评估 | RAGAS (context_relevancy / faithfulness) |
| 生产级 RAG | Haystack Pipeline + REST API |
| Graph RAG | Microsoft GraphRAG / FastGraphRAG |
| 多模态 RAG | VibeCut 你自己已经做了! (ASR+VLM → 文本 → 检索) |

---

> 文档版本: v0.12 | 生成日期: 2026-08-04
