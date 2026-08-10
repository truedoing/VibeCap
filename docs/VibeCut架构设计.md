# VibeCut 架构设计 v3

> 统一电视剧与口播采访的工作流。v1.1 架构重构后。
> 2026-08-08 · 基于 FastAPI + 模块化架构。

---

## 一、全局工作流

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│  Phase 1     │  Phase 2     │  Phase 3     │  Phase 4     │
│  数据台·初步  │  编剧台       │  数据台·全面   │  分镜台       │
│  (素材准备)   │  (撰写脚本)   │  (深度索引)    │  (分镜匹配)   │
├──────────────┼──────────────┼──────────────┼──────────────┤
│              │              │              │              │
│ LLM: 批量处理 │ LLM: 交互辅助 │ LLM: 批量校对 │ 纯工程        │
│ 让人能看懂素材 │ 人主导+AI配合  │ 让机器能搜素材 │ 画面匹配+组装 │
│              │              │              │              │
└──────────────┴──────────────┴──────────────┴──────────────┘
        ↑ 全流程 AI 贯穿，区别在于调用方式（批量 vs 交互）↑
```

Phase A 和 Phase B 都在数据台，但目的不同、时机不同：

| | Phase A (写前) | Phase B (写后) |
|---|---|---|
| **目的** | 人看懂素材 | 机器搜索素材 |
| **输入** | 原始视频 | segments.json (脚本) |
| **产出** | 可浏览的文案/摘要 | 语义索引 + 质量报告 |
| **电视剧** | ASR + VLM初步分析 | 解说ASR校对 + BGE索引 + 数据清洗 |
| **口播** | ASR + LLM分类 + LLM分段 | ASR校对 + BGE索引 + 质量评分 |

---

## 二、后端架构 (v1.1 重构后)

### 2.1 模块分层

```
vibecut-server/
├── main.py                     ← FastAPI 入口 + 路由注册 (805行)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析 (94行)
├── db.py                       ← SQLite 数据库层
│
├── handlers/                   ← 接口处理器 (2,107行)
│   ├── search.py               ← 6种搜索引擎 (语义/关键词/混合/ASR优先/深度/口播)
│   ├── tasks.py                ← 任务 CRUD (创建/状态/删除/列表)
│   ├── script_gen.py           ← AI脚本生成 (v3流水线/v4故事优先/精切 SSE)
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/片段提取/预览/导出)
│   ├── dialogue.py             ← 对话+台词 (chat/dialogue_match/storyboard/analyze)
│   └── static.py               ← SPA前端回退 + 任务目录文件服务
│
├── lib/                        ← 共享基础设施 (377行)
│   ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo, 消除10种重复)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← 可复用SSE发射器 + 心跳
│   ├── env.py                  ← 统一.env加载
│   └── subprocess_runner.py    ← 统一子进程执行器
│
├── script_agents.py            ← 编剧台 AI Agent (v3搜索+v4故事优先)
├── refine_segments.py          ← 口播精切引擎
└── (独立脚本...)
    ├── build_index.py          ← BGE索引统一入口
    ├── analyze_episodes.py     ← 电视剧: 场景+ASR+VLM
    ├── classify_transcript.py  ← 口播: LLM分类
    ├── clean_interview_data.py ← 口播: 清洗+说话人
    └── export_capcut.py        ← 剪映草稿导出
```

### 2.2 框架选型

| 维度 | v1.0 (`http.server`) | v1.1 (FastAPI) |
|---|---|---|
| 路由 | 手动 if/elif 链 (200行) | `@app.get/post` 装饰器 |
| 文件上传 | 手写 150行 boundary 解析 | `UploadFile` 自动 |
| CORS | 每个端点手动加头 | `CORSMiddleware` 一行 |
| SSE | 手写 `wfile.write` (3次重复) | `StreamingResponse` |
| API 文档 | ❌ | ✅ Swagger (`/docs`) |
| 输入校验 | ❌ 裸 `json.loads` | Pydantic (可逐步加) |

---

## 三、数据台：双阶段流水线

### 3.1 Phase A — 素材准备

```
电视剧流水线:                       口播流水线:
  analyze_episodes.py                classify_transcript.py
  ├─ 场景切分(10s)                   ├─ LLM分类 (content/meta/guide/filler)
  ├─ ASR转写(faster-whisper)         ├─ LLM分段 (5-8个主题组)
  └─ VLM分析(MiMo)                   └─ 生成标准化文案

                                      clean_interview_data.py
                                      ├─ LLM文本清洗 (去废词/口误)
                                      ├─ 说话人识别 (host/guest)
                                      └─ 输出 classified_enhanced.json

产出:                              产出:
  sources/ep{N}/                      sources_clean/
  ├─ asr_result.json                  ├─ classified.json
  ├─ vlm_analysis.json                ├─ classified_enhanced.json
  └─ scenes.json                      ├─ segmented.json
                                      └─ content_report.json
```

### 3.2 Phase B — 深度索引

```
电视剧流水线:                       口播流水线:
  cross_calibrate.py                 build_index.py (自动识别项目类型)
  ├─ ASR ↔ VLM 交叉校准              ├─ 优先使用 enhanced 数据
  │                                   ├─ speaker边界断开分块
  clean_data.py                       ├─ guest-only 建索引
  ├─ ASR碎片合并                      └─ BGE 768维 → .npy + .json
  ├─ VLM场景智能合并
  │                                   semantic_embeddings.npy
  build_index.py                      semantic_metas.json
  └─ BGE语义索引重建
```

---

## 四、编剧台：通用脚本工厂

### 4.1 两条流水线

#### v3 搜索流水线 (run_pipeline) — 电视剧/有索引的场景

```
策划师(LLM) → 文案师(BGE搜索) → 精编师(LLM压缩) → 审核师(LLM审核+修复)
                    ↕
              BGE 语义索引
```

**API**: `POST /script/generate_script_stream` (SSE 流式)

#### v4 故事优先流水线 (story_first_pipeline) — 口播采访

```
LLM 通读全部 ASR → 理解完整故事 → 一次性输出分组段落脚本
```

**API**: `POST /script/generate_story_first` (SSE 流式, ~12s 完成)

**对比**:

| | v3 搜索流水线 | v4 故事优先 |
|---|---|---|
| 策略 | 逐段搜索 → 拼句子 | 通读全文 → 设计故事 |
| 调用次数 | 4-8 次 LLM + 8 次 BGE | 1 次 LLM |
| 耗时 | ~40s | ~12s |
| 段落结构 | 扁平句子列表 | 分组段落（section → clips） |
| 适用 | 电视剧（多集、多镜头） | 口播采访（单文件、单镜头） |

---

## 五、分镜台：解说词→镜头匹配

```
消费 segments.json，按项目类型选择策略:

电视剧:
  narration_text → BGE语义搜索 → VLM画面匹配 → Elah 4轨
  4轨: 原声主镜头 | 原声音频 | 补充镜头 | 旁白TTS

口播:
  highlight_text → 源视频时间戳定位 → 跳切串联
  可走两条路径:
    A. Elah编辑器 (同电视剧)
    B. CapCut自动导出 (export_capcut.py)
```

---

## 六、目录结构

```
VibeCut/
├── vibecut-server/
│   ├── main.py                     ← FastAPI 入口
│   ├── config.py
│   ├── db.py
│   ├── lib/                        ← 共享基础设施
│   ├── handlers/                   ← 接口处理器
│   ├── script_agents.py            ← AI Agent
│   ├── refine_segments.py          ← 精切引擎
│   ├── build_index.py              ← BGE索引
│   └── (数据处理脚本...)
│
├── vibecut-web/
│   └── src/
│       └── pages/
│           ├── DataDesk.jsx
│           ├── PlanningDesk.jsx
│           └── VibeEdit.jsx
│
├── projects/
│   ├── 都挺好.json
│   └── 杨老师教育.json
│
├── 都挺好/                         ← 电视剧项目
│   ├── sources/ep{N}/
│   ├── sources_clean/ep{N}/
│   ├── proxies/
│   ├── semantic_embeddings.npy
│   └── tasks/
│
└── 杨老师教育/                     ← 口播项目
    ├── sources/
    ├── sources_clean/
    │   ├── classified.json
    │   ├── classified_enhanced.json
    │   ├── semantic_embeddings.npy
    │   └── semantic_metas.json
    ├── proxies/
    └── tasks/
```

---

> 最后更新：2026-08-08 · v1.1.0
