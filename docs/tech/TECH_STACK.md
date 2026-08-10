# VibeCut 技术架构文档 v1.2

> AI 影视解说/口播导演台 — 从语言到框架到库到模型的全栈技术图谱

---

## 目录

1. [总览](#总览)
2. [语言层](#1-语言层)
3. [运行时与包管理](#2-运行时与包管理)
4. [后端框架与服务](#3-后端框架与服务)
5. [前端框架与构建](#4-前端框架与构建)
6. [视频编辑引擎](#5-视频编辑引擎)
7. [UI 组件体系](#6-ui-组件体系)
8. [AI/ML 框架与库](#7-aiml-框架与库)
9. [AI 模型层](#8-ai-模型层)
10. [媒体处理工具](#9-媒体处理工具)
11. [数据存储](#10-数据存储)
12. [外部 API 集成](#11-外部-api-集成)
13. [数据流架构](#12-数据流架构)
14. [部署方式](#13-部署方式)

---

## 总览

```
┌─────────────────────────────────────────────────────────┐
│                   🧠 AI 模型层                           │
│   BGE-base-zh  │  faster-whisper  │  DeepSeek  │  MiMo VLM  │  F5-TTS  │
├─────────────────────────────────────────────────────────┤
│                   📦 AI/ML 框架层                        │
│   sentence-transformers  │  numpy  │  faster-whisper  │  PyTorch  │
├─────────────────────────────────────────────────────────┤
│                   🔧 后端服务层 (Python 3.12)             │
│   FastAPI  │  Uvicorn  │  SQLite  │  threading  │  subprocess  │
├─────────────────────────────────────────────────────────┤
│                   🖥️ 前端框架层 (JavaScript)             │
│   React 19  │  React Router 7  │  Vite 8  │  Tailwind 4  │
├─────────────────────────────────────────────────────────┤
│                   🎬 视频编辑引擎                        │
│   @elah/core  │  @elah/editor  │  @elah/timeline         │
├─────────────────────────────────────────────────────────┤
│                   🎨 UI 组件层                           │
│   Radix UI  │  Lucide  │  CVA  │  clsx  │  tailwind-merge │
├─────────────────────────────────────────────────────────┤
│                   🎞️ 媒体处理                            │
│   ffmpeg  │  ffprobe                                     │
├─────────────────────────────────────────────────────────┤
│                   🗄️ 数据存储                            │
│   SQLite  │  JSON  │  NumPy .npy  │  localStorage         │
└─────────────────────────────────────────────────────────┘
```

---

## 1. 语言层

| 语言 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.12 | 后端全栈：FastAPI 服务、AI 流水线、数据库、视频处理编排 |
| **JavaScript (ES Modules)** | ES2024+ | 前端全栈：UI 渲染、视频编辑器集成、状态管理 |
| **JSX** | React 19 | 组件模板（非 TypeScript，纯 JSX） |
| **CSS** | Tailwind 4 + 内联样式 | 样式系统（混合方案） |

**选型特点：** 前后端均为纯 JS/Python，无 TypeScript、无类型标注。v1.1 后端从 `http.server` 升级至 **FastAPI** 以获取自动文档、请求校验和模块化路由能力。

---

## 2. 运行时与包管理

| 组件 | 技术 | 说明 |
|------|------|------|
| **Python 解释器** | `/opt/anaconda3/bin/python3` | Anaconda 发行版，硬编码路径 |
| **Python 包管理** | pip + `requirements.txt` | 仅 2 个显式依赖 |
| **Node.js 运行时** | — | Vite 开发服务器 |
| **前端包管理** | npm | `package.json` 管理 18 个生产依赖 |
| **虚拟环境** | 无 | 直接使用 Anaconda 全局环境 |

**Python 依赖清单 (v1.1)**

```
numpy>=1.24
sentence-transformers>=2.7
fastapi>=0.112            # (v1.1 新增) Web 框架
uvicorn>=0.35             # (v1.1 新增) ASGI 服务器
python-multipart          # (v1.1 新增) 文件上传支持
faster-whisper            # (隐式依赖)
python-docx               # (隐式依赖, DOCX 解析)
torch                     # (隐式依赖, F5-TTS 推理)
f5-tts                    # (隐式依赖, 语音克隆)
zhconv                    # (可选, 繁简转换)
```

### 前端依赖清单

```json
{
  "production": {
    "react": "19.2.7",
    "react-dom": "19.2.7",
    "react-router-dom": "7.18.1",
    "@elah/core": "0.3.2",
    "@elah/editor": "0.3.2",
    "@elah/timeline": "0.3.2",
    "@radix-ui/*": "8 packages",
    "@tailwindcss/vite": "4.3.3",
    "tailwindcss": "4.3.3",
    "tailwindcss-animate": "1.0.7",
    "tailwind-merge": "3.6.0",
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "lucide-react": "1.27.0"
  },
  "dev": {
    "vite": "8.1.1",
    "@vitejs/plugin-react": "6.0.3",
    "oxlint": "1.71.0"
  }
}
```

---

## 3. 后端框架与服务

### 3.1 HTTP 服务 (v1.1: FastAPI)

| 组件 | 技术 | 说明 |
|------|------|------|
| **Web 框架** | **FastAPI** (0.112) | Async-capable，自动 Swagger 文档，Pydantic 校验 |
| **ASGI 服务器** | **Uvicorn** (0.35) | 高性能异步服务器 |
| **并发模型** | Uvicorn worker (async) | 替代旧 ThreadingMixIn |
| **路由** | FastAPI 路由装饰器 | `@app.get/post`，模块化 `handlers/` |
| **流式响应** | `StreamingResponse` + SSE | 通用生成器包装，复用 `lib/sse.py` |
| **静态文件** | `FileResponse` + SPA fallback | handlers/static.py |
| **端口** | 8765 (默认) | 可配置 |

### 3.2 旧版 (v1.0, server.py 兼容保留)

| 组件 | 技术 | 说明 |
|------|------|------|
| **HTTP 服务器** | `http.server.HTTPServer` | Python 标准库，线程池模式 |
| **并发模型** | `socketserver.ThreadingMixIn` | 每请求一线程 |

### 3.2 核心模块

```
vibecut-server/
├── server.py                  ← 主服务: API + SSE + 静态文件 + 后台流水线
├── db.py                      ← SQLite 数据库层 (VibeCutDB 类)
├── script_agents.py           ← 编剧台 AI Agent 系统
│   ├── run_pipeline()         ← v3 搜索流水线 (规划→BGE搜索→写作→审核)
│   └── story_first_pipeline() ← v4 故事优先 (LLM通读→单次生成)
├── refine_segments.py         ← 口播精切引擎 (粗段→sub_clips KEEP/CUT)
├── build_index.py             ← BGE 语义索引统一入口
├── clean_interview_data.py    ← LLM 文本清洗 + 说话人识别
├── classify_transcript.py     ← LLM ASR 四层分类 (content/guide/meta/filler)
├── segment_transcript.py      ← LLM 主题分段
├── analyze_episodes.py        ← 电视剧: 场景切分 + ASR + VLM
├── cross_calibrate.py         ← ASR ↔ VLM 交叉校准
├── clean_data.py              ← 电视剧: 数据清洗 + 场景合并
├── export_capcut.py           ← 剪映草稿导出
├── generate_proxies.py        ← 540p 代理视频生成
├── migrate_db.py              ← DB 迁移工具
├── f5tts_clone.py             ← F5-TTS 语音克隆 (实验性)
├── tts_voice_clone.py         ← MiMo TTS 语音克隆 (实验性)
└── regression_check.py        ← 质量回归检查
```

### 3.3 关键 API 端点

| 端点 | 方法 | 说明 | 响应类型 |
|------|------|------|----------|
| `/search?q=&mode=` | GET | BGE 语义搜索 / 关键词搜索 / 混合搜索 | JSON |
| `/segments.json?task=` | GET | 任务分段数据 (含 sub_clips) | JSON |
| `/script/generate_script_stream` | POST | v3 搜索流水线 | SSE 流 |
| `/script/generate_story_first` | POST | v4 故事优先脚本生成 | SSE 流 |
| `/script/refine` | POST | 精切流水线 | SSE 流 |
| `/chat?task=` | POST | AI 对话式搜索 | JSON |
| `/proxies/manifest` | GET | 代理视频清单 | JSON |
| `/picks` | GET/POST | 素材选择同步 | JSON |
| `/data/quality` | GET | 剧集质量报告 | JSON |
| `/data/process` | POST | 后台加工流水线 | JSON |
| `/status` | GET | 健康检查 | JSON |

---

## 4. 前端框架与构建

### 4.1 框架栈

| 组件 | 技术 | 说明 |
|------|------|------|
| **UI 框架** | React 19.2 | 函数组件 + Hooks |
| **路由** | React Router 7.18 | 客户端 SPA 路由 |
| **构建工具** | Vite 8.1 | HMR 热更新, 代理转发 |
| **CSS 框架** | Tailwind CSS 4.3 | 原子化 CSS + CSS 变量 |
| **Linter** | oxlint 1.71 | Rust 实现, 替代 ESLint |

### 4.2 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | Home | 项目：项目管理 |
| `/:project/:task/planning` | PlanningDesk | 编剧台：三栏布局 (素材/脚本/AI) |
| `/:project/:task/vibe` | VibeEdit | 分镜台：多轨时间轴编辑 |
| `/data` | DataDesk | 数据台：流水线管理 + 质量监控 |

### 4.3 Vite 代理配置

前端开发服务器 (3000) 将 20+ API 路径代理到后端 (8765)：

```
/search, /chat, /script, /segments.json, /proxies,
/picks, /dramas, /tasks, /data, /export, /asr, /status
```

### 4.4 状态管理

| 方案 | 用途 |
|------|------|
| **React Context** (`ProjectContext`) | 任务级全局状态 (picks, timeline, segments) |
| **Zustand** (Elah 内部) | 时间轴引擎状态 (playback, tracks, mediaLibrary, selection) |
| **localStorage** | 前端数据持久化 (项目缓存、任务列表) |
| **useState/useRef** | 组件局部 UI 状态 |

---

## 5. 视频编辑引擎

### Elah 生态系统 (v0.3.2)

| 包 | 用途 | 关键 API |
|----|------|----------|
| `@elah/core` | 核心引擎 | 播放控制、帧计算、WebGL2 渲染、媒体管理 |
| `@elah/editor` | React SDK | `EditorProvider`, `Preview`, `Timeline`, `createDefaultDemuxerFactory` |
| `@elah/timeline` | 时间轴 UI | 多轨剪辑、拖拽裁剪、标尺游标 |

### 时间轴规格

| 项目类型 | 轨道数 | 帧率 | 分辨率 |
|----------|--------|------|--------|
| **口播 (interview)** | 2 轨 | 30fps | 1920×1080 |
| **电视剧 (drama)** | 4 轨 | 25fps | 1920×1080 |

### 关键能力

- **WebGL2 预览**：浏览器端实时视频预览
- **解复用器工厂**：代理视频 (540p) 高效加载
- **Web Worker 导出**：`ExportWorker` 后台 MP4 导出
- **联动编辑**：视频/音频 clip 配对同步 (Monkey-patch 实现)
- **程序式建轨**：`timelineBuilder.js` 自动从 picks 构建 Elah Project

---

## 6. UI 组件体系

### 6.1 组件库

| 库 | 版本 | 说明 |
|----|------|------|
| **Radix UI** | 8 个包 | 无样式无障碍 UI 原语 |
| **Lucide React** | 1.27 | 图标库 |
| **shadcn/ui** | 配置兼容 | 设计模式 (CVA + clsx + tailwind-merge) |

### 6.2 Radix UI 包清单

| 包 | 用途 |
|----|------|
| `@radix-ui/react-dialog` | 模态对话框 |
| `@radix-ui/react-dropdown-menu` | 下拉菜单 |
| `@radix-ui/react-popover` | 弹出面板 |
| `@radix-ui/react-scroll-area` | 自定义滚动区 |
| `@radix-ui/react-select` | 选择下拉 |
| `@radix-ui/react-separator` | 分割线 |
| `@radix-ui/react-slot` | 插槽组合 |
| `@radix-ui/react-tabs` | 页签切换 |
| `@radix-ui/react-tooltip` | 工具提示 |

### 6.3 设计系统

| 文件 | 内容 |
|------|------|
| `src/styles/theme.js` | 设计令牌 (颜色、间距、字体、圆角) |
| `src/styles/mixins.js` | 样式工厂函数 (btn, card, input, panel, flexRow...) |
| `src/index.css` | Tailwind CSS 变量 + `@theme` 配置 |
| `src/lib/utils.js` | `cn()` 工具: `clsx` + `tailwind-merge` |

### 6.4 核心业务组件

| 组件 | 说明 |
|------|------|
| `SourceInspector` | PR 风格源检视器 (纯 video + DOM 叠加) |
| `ScriptPanel` | 脚本面板 (粗段/精切 sub_clips 自适应) |
| `ChatPanel` | AI 搜索面板 (口播/影剧自适应, SSE 流式渲染) |
| `TimelineControls` | 播放控制栏 (播放/暂停/缩放/分割/导出) |
| `StoryboardPanel` | AI 分镜推荐面板 |

---

## 7. AI/ML 框架与库

| 库 | 用途 | AI 领域 |
|----|------|---------|
| **sentence-transformers** | BGE 模型加载 + `encode()` 推理 | NLP / 语义嵌入 |
| **numpy** | 向量矩阵运算: `np.dot` 余弦相似度, `np.argsort` Top-K | 数值计算 / 向量检索 |
| **faster-whisper** | Whisper CTranslate2 后端, int8 量化推理 | 语音识别 / ASR |
| **CTranslate2** | faster-whisper 推理后端 (隐式依赖) | 模型推理加速 |
| **PyTorch** (`torch`) | F5-TTS 模型推理后端 (隐式依赖) | 深度学习框架 |
| **HuggingFace Hub** | 模型下载 (通过 hf-mirror.com 镜像) | 模型分发 |

### BGE 向量检索流程

```
文本片段 → SentenceTransformer.encode() → 768维向量
                                           ↓
查询文本 → encode() → q_emb               np.dot(semantic_emb, q_emb)
                                           ↓
                                    np.argsort() → Top-K
```

**设计特点：** 全量向量加载到内存，NumPy 矩阵乘法一次完成检索，无需向量数据库 (Milvus/Pinecone)。

---

## 8. AI 模型层

### 8.1 模型总览

| 模型 | 类型 | 部署 | 用途 |
|------|------|------|------|
| **BAAI/bge-base-zh-v1.5** | 文本嵌入 | 本地 CPU | 中文语义搜索索引 |
| **faster-whisper small** | 语音识别 | 本地 CPU | 音频→文本 (int8 量化) |
| **DeepSeek-Chat** | 大语言模型 | 云端 API | 脚本生成、数据清洗、内容分类、说话人识别 |
| **MiMo v2.5** | 视觉语言模型 | 云端 API | 电视剧画面场景分析 |
| **MiMo v2.5 TTS** | 语音合成 | 云端 API | 零样本语音克隆 (实验) |
| **F5-TTS** | 语音合成 | 本地 CPU | 零样本语音克隆 (实验) |

### 8.2 BAAI/bge-base-zh-v1.5

| 属性 | 值 |
|------|-----|
| **架构** | BERT-base (Transformer Encoder) |
| **向量维度** | 768 |
| **最大长度** | 512 tokens |
| **推理设备** | CPU |
| **批大小** | 32-64 |
| **归一化** | L2 normalize |
| **离线模式** | `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` |
| **下载源** | `https://hf-mirror.com` (HF 国内镜像) |
| **加载方式** | `SentenceTransformer("BAAI/bge-base-zh-v1.5", device="cpu")` |

### 8.3 faster-whisper

| 属性 | 值 |
|------|-----|
| **模型大小** | `small` (电视剧) / `base` (口播旁白) |
| **推理引擎** | CTranslate2 |
| **量化** | int8 |
| **设备** | CPU |
| **语言** | zh (中文) |
| **Beam Size** | 5 |
| **VAD 过滤** | 开启, min_silence_duration_ms=500 |
| **输入** | 16kHz 单声道 WAV |
| **输出** | 分段文本 + 时间戳 + 置信度 |

### 8.4 DeepSeek-Chat

| 属性 | 值 |
|------|-----|
| **API 端点** | `https://api.deepseek.com/v1/chat/completions` |
| **模型名** | `deepseek-chat` |
| **上下文窗口** | 128K tokens |
| **温度范围** | 0.2–0.7 (任务依赖) |
| **最大输出** | 200–8000 tokens |
| **重试策略** | 最多 3 次, 间隔 3s |
| **超时** | 15–180s |
| **输出格式** | JSON mode (结构化输出) |

**承担角色 (Multi-Agent 系统):**

| Agent | 职责 |
|-------|------|
| `planning_agent` | 叙事结构设计 |
| `writer_agent` | 从 ASR 素材中选取句子 |
| `editor_agent` | 脚本压缩 + 时间多样性 |
| `reviewer_agent` | 质量审核 + 评分 |
| `story_first_pipeline` | 通读全部 ASR, 单次生成完整脚本 |
| 分类器 | ASR 四层分类: content/guide/meta/filler |
| 清洗器 | 文本纠错 + 说话人识别 |
| 分段器 | 主题分段 |

### 8.5 MiMo v2.5 (VLM)

| 属性 | 值 |
|------|-----|
| **API 端点** | `https://api.xiaomimimo.com/v1/chat/completions` |
| **模型名** | `mimo-v2.5` |
| **输入** | 文本 + base64 编码关键帧图像 |
| **输出** | 场景描述、深度分析、人物情感、结构化字幕 |
| **用途** | 电视剧画面理解、搜索查询扩展、LLM 重排序 |

### 8.6 模型组合策略

```
口播管线:
  ASR 音频 → faster-whisper (ASR) → DeepSeek (分类+清洗)
           → BGE (索引) → DeepSeek (脚本生成+精切)
           → CapCut 导出

电视剧管线:
  视频 → faster-whisper (ASR) + MiMo VLM (画面分析)
       → 交叉校准 → 数据清洗 → BGE (索引)
       → DeepSeek (搜索+脚本) → 分镜台
```

**关键设计原则：**
- **本地+云端混合**：嵌入和 ASR 本地推理（低延迟、零成本），LLM/VLM 云端调用（高质量）
- **多模态融合**：音频转文本 + 画面转文本，统一为文本检索
- **增量索引**：预处理完成后一次性构建 BGE 索引，查询时全量内存计算

---

## 9. 媒体处理工具

### ffmpeg / ffprobe

| 场景 | 命令参数 | 说明 |
|------|----------|------|
| **代理视频生成** | `-vf scale=960:540 -crf 28 -preset fast -g 50 -r 25 -c:a aac -b:a 64k` | 1080p→540p 轻量代理 |
| **音频提取** | `-vn -ar 16000 -ac 1` | ASR 预处理 |
| **精切片段导出** | `-c:v libx264 -preset ultrafast -crf 18 -c:a aac -b:a 256k -movflags +faststart` | 高质量片段 |
| **时长探测** | `ffprobe -v quiet -show_entries format=duration -of csv=p=0` | 视频元数据 |
| **场景检测** | 固定时长切分 (非 scdet) | 避免切太碎 |

### 代理视频规格

| 参数 | 值 |
|------|-----|
| 分辨率 | 960×540 |
| CRF | 28 |
| Preset | fast |
| GOP | 50 (2秒关键帧间隔) |
| 帧率 | 25fps |
| 音频码率 | 64kbps |

---

## 10. 数据存储

### 10.1 SQLite 数据库

| 属性 | 值 |
|------|-----|
| **文件** | `vibecut.db` |
| **模式** | WAL (Write-Ahead Logging) |
| **外键** | ON |
| **超时** | 5000ms |
| **连接** | `threading.local()` 线程安全 |

**数据表结构：**

```
dramas          — 项目注册 (name, slug, type)
episodes        — 每集元数据 + ASR/VLM 质量统计
index_entries   — BGE 语义索引条目 (type, start, end, text, weight)
tasks           — 剪辑任务 (status, segments_count, duration, picks_json, timeline_json)
task_segments   — 任务分段 (source_start, source_end, section_role, note, sentences_json)
quality_reports — 质量评分 (ASR, VLM, subtitle, overall)
```

### 10.2 文件存储

| 格式 | 用途 | 路径示例 |
|------|------|----------|
| **JSON** | 分段数据、项目配置、ASR/VLM 中间产物 | `tasks/*/segments.json` |
| **NumPy .npy** | BGE 语义向量 (mmap 零拷贝加载) | `semantic_embeddings.npy` |
| **Pickle .pkl** | BGE 索引 (遗留格式) | `semantic_index.pkl` |
| **localStorage** | 前端项目缓存、任务列表 | 浏览器端 |

### 10.3 segments.json 结构 (v0.12)

```json
{
  "segments": [{
    "seg_id": 0,
    "source_start": 2.5,
    "source_end": 16.9,
    "sub_clips": [
      {
        "start": 2.5, "end": 6.2,
        "text": "...",
        "decision": "KEEP",
        "speaker": "guest"
      }
    ],
    "refine_stats": { "keep": 2, "cut": 1, "keep_duration": 12.0, "cut_duration": 2.5 }
  }],
  "refined": true,
  "refine_summary": { "keep": 22, "cut": 10, "keep_duration": 168.2, "cut_duration": 11.1 }
}
```

---

## 11. 外部 API 集成

| API | 端点 | 模型 | 认证 | 协议 |
|-----|------|------|------|------|
| **DeepSeek** | `api.deepseek.com/v1/chat/completions` | `deepseek-chat` | `Bearer $DEEPSEEK_API_KEY` | OpenAI 兼容 |
| **MiMo** | `api.xiaomimimo.com/v1/chat/completions` | `mimo-v2.5`, `mimo-v2.5-tts-voiceclone` | `Bearer $MIMO_API_KEY` | OpenAI 兼容 |
| **HuggingFace** | `hf-mirror.com` (国内镜像) | BGE 模型权重 | 无 | HTTPS 下载 |

**环境变量：**

```bash
DEEPSEEK_API_KEY=sk-xxx   # 编剧台 LLM + 数据清洗
MIMO_API_KEY=sk-xxx       # VLM 画面分析 (仅电视剧)
MIMO_API_URL=https://api.xiaomimimo.com/v1
VITE_API_BASE=http://localhost:8765  # 前端 API 基址
```

---

## 12. 数据流架构

### 12.1 口播管线

```
┌──────────┐    ┌──────────────┐    ┌─────────────────┐
│ 原始视频  │ →  │ faster-whisper │ →  │ sources/*.json   │
│ (口播)   │    │ 本地 ASR      │    │ (ASR 原始文本)    │
└──────────┘    └──────────────┘    └────────┬────────┘
                                             │
                    ┌────────────────────────┘
                    ▼
┌──────────────────────────────────────────────────────┐
│               DeepSeek API (LLM)                       │
│                                                        │
│  classify_transcript.py  ──→  四层分类                 │
│       content / guide / meta / filler                  │
│                         │                              │
│  clean_interview_data.py ──→  文本清洗 + 说话人识别     │
│       classified_enhanced.json                         │
│                         │                              │
│  segment_transcript.py   ──→  主题分段                 │
│       segmented.json                                   │
└──────────────────────────┬───────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────┐
│                  BGE 索引构建                          │
│  build_index.py                                        │
│  SentenceTransformer("BAAI/bge-base-zh-v1.5")         │
│  → semantic_embeddings.npy + semantic_metas.json       │
└──────────────────────────┬───────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────┐
│              编剧台 (AI 脚本生成)                       │
│                                                        │
│  script_agents.py                                      │
│  ┌─────────────────────────────────────────┐          │
│  │ v3 搜索流水线 (SSE 流式)                  │          │
│  │ planning → BGE搜索 → writing → reviewing │          │
│  └─────────────────────────────────────────┘          │
│  ┌─────────────────────────────────────────┐          │
│  │ v4 故事优先 (SSE 流式)                    │          │
│  │ LLM 通读全文 → 单次输出完整脚本             │          │
│  └─────────────────────────────────────────┘          │
│                         │                              │
│  refine_segments.py     │                              │
│  粗段 + classified_enhanced → sub_clips KEEP/CUT       │
└──────────────────────────┬───────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────┐
│              分镜台 / 导出                              │
│                                                        │
│  VibeEdit.jsx  ← segments.json (含 sub_clips)         │
│  Elah 引擎: 仅 KEEP sub_clips → 时间轴                  │
│                                                        │
│  export_capcut.py → 剪映草稿 JSON                       │
│  CUT 项音量=5% (便于识别删除)                            │
└──────────────────────────────────────────────────────┘
```

### 12.2 电视剧管线

```
┌──────────┐    ┌─────────────────────────────────────┐
│ 原始视频  │ →  │  analyze_episodes.py                  │
│ (46集)   │    │  ┌─────────────────────────────────┐ │
└──────────┘    │  │ faster-whisper small → ASR 文本  │ │
                │  │ MiMo v2.5 (VLM) → 画面分析       │ │
                │  └─────────────────────────────────┘ │
                └────────────────┬────────────────────┘
                                 │
                ┌────────────────▼────────────────────┐
                │  cross_calibrate.py                  │
                │  ASR ↔ VLM 交叉校准                   │
                │  时间窗口匹配 + 双向补漏 + 置信度加权    │
                └────────────────┬────────────────────┘
                                 │
                ┌────────────────▼────────────────────┐
                │  clean_data.py                       │
                │  数据清洗 + 场景合并                   │
                └────────────────┬────────────────────┘
                                 │
                ┌────────────────▼────────────────────┐
                │  build_index.py                      │
                │  BGE 语义索引 (VLM 描述 + ASR 文本)    │
                └────────────────┬────────────────────┘
                                 │
                                 ▼
                    编剧台 → 分镜台 → 导出
```

### 12.3 SSE 流式协议

```
Client                          Server
  │                                │
  │── POST /script/generate ──────→│
  │                                │── Agent 1: planning
  │←── data: {"event":"step",     │
  │           "agent":"planning"}  │
  │                                │── Agent 2: writing + BGE search
  │←── data: {"event":"step",     │
  │           "agent":"writing"}   │
  │                                │── Agent 3: reviewing
  │←── data: {"event":"result",   │
  │           "segments":[...]}    │
  │←── data: {"event":"done"}     │
  │                                │
```

---

## 13. 部署方式

### 13.1 开发环境

```bash
# 后端 (端口 8765)
cd vibecut-server
/opt/anaconda3/bin/python3 server.py --project 杨老师教育 --task 0801学习新东方

# 前端 (端口 3000, 代理到 8765)
cd vibecut-web
npm run dev
```

### 13.2 生产部署

```bash
# deploy.sh — 单命令部署
./deploy.sh [project] [task] [port]

# 流程:
# 1. git pull origin main
# 2. npm run build (前端构建)
# 3. 杀掉旧进程
# 4. nohup 启动后端
# 5. curl /status 验证
```

| 属性 | 说明 |
|------|------|
| **容器化** | 无 Docker |
| **CI/CD** | 无 |
| **进程管理** | `nohup` + 手动 kill |
| **静态资源** | Python 后端直接 serve 前端 dist/ |
| **反向代理** | 无 (开发时 Vite proxy, 生产直连) |

---

## 附录: AI 技术关键词索引

| 关键词 | 对应技术 | 文件位置 |
|--------|----------|----------|
| 语义搜索 / Semantic Search | BGE + NumPy | `server.py`, `build_index.py` |
| 向量嵌入 / Embedding | sentence-transformers | `build_index.py` |
| 语音识别 / ASR | faster-whisper | `analyze_episodes.py`, `asr_narration.py` |
| 视觉语言模型 / VLM | MiMo v2.5 | `analyze_episodes.py` |
| 大语言模型 / LLM | DeepSeek-Chat | `script_agents.py`, `server.py` |
| 多智能体系统 / Multi-Agent | Agent 流水线 | `script_agents.py` |
| 流式响应 / SSE | Server-Sent Events | `server.py` |
| 文本分类 | LLM 四层分类 | `classify_transcript.py` |
| 说话人识别 | LLM 说话人标注 | `clean_interview_data.py` |
| 检索增强生成 / RAG | BGE 搜索 + LLM 生成 | `script_agents.py` |
| 语音克隆 / Voice Cloning | F5-TTS + MiMo TTS | `f5tts_clone.py`, `tts_voice_clone.py` |
| 视频理解 | VLM 多帧分析 | `analyze_episodes.py` |
| 交叉校准 / Calibration | ASR ↔ VLM 对齐 | `cross_calibrate.py` |
| 视频编辑引擎 / NLE | Elah (WebGL2) | `@elah/editor` |
| 代理视频 / Proxy | ffmpeg 540p 转码 | `generate_proxies.py` |
| 非线性编辑导出 / NLE Export | CapCut/剪映草稿 JSON | `export_capcut.py` |

---

> 文档版本: v0.12 | 生成日期: 2026-08-04 | 对应代码版本: 3b104dc
