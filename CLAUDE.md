# VIBECAP — AI 影视解说/口播剪辑台 v0.11

## 项目类型

| 类型 | 项目 | 源素材 | 索引方式 |
|---|---|---|---|
| drama | 都挺好 | 46集 1080p | BGE (ASR + VLM) |
| interview | 杨老师教育 | 口播采访 | BGE (ASR, guest-only, speaker边界) |

## 目录

```
VIBECAP/
├── vibecap-server/            ← Python 后端 (端口8765)
│   ├── server.py              ← 主服务 + API
│   ├── db.py                  ← SQLite (dramas/episodes/tasks/task_segments/index_entries)
│   ├── script_agents.py       ← 策划台 AI: v3搜索流水线 + v4故事优先
│   ├── build_index.py         ← BGE索引统一入口 (--project)
│   ├── clean_interview_data.py← 口播: LLM清洗+说话人识别
│   ├── classify_transcript.py ← 口播: LLM ASR分类
│   ├── generate_proxies.py    ← 540p代理视频
│   └── (analyze_episodes/cross_calibrate/clean_data — 电视剧管线)
│
├── vibecap-web/               ← React 前端 (Vite, 端口3000)
│   └── src/pages/
│       ├── PlanningDesk.jsx   ← 策划台: 主题+AI生成脚本
│       ├── VibeEdit.jsx       ← 沉浸剪辑台: 源检视器+时间轴
│       ├── DataDesk.jsx       ← 数据台: 流水线管理
│       └── Home.jsx           ← 任务台
│
├── docs/                      ← 文档
│   ├── VIBECAP架构设计.md
│   ├── PLANNING_DESK.md       ← 策划台算法
│   ├── DATA_PIPELINE.md       ← 数据管线
│   └── VIBE_EDITING.md        ← 剪辑台设计
│
├── projects/                  ← 项目配置
│   ├── 都挺好.json
│   └── 杨老师教育.json
│
├── 都挺好/                    ← 电视剧数据
│   ├── sources/ep{N}/         ← 原始ASR+VLM
│   ├── sources_clean/ep{N}/   ← 清洗后数据
│   ├── proxies/               ← 540p代理
│   ├── semantic_embeddings.npy ← BGE索引
│   └── tasks/                 ← 任务数据
│
├── 杨老师教育/                ← 口播数据
│   ├── sources/               ← 原始ASR
│   ├── sources_clean/         ← classified / enhanced / segmented
│   ├── proxies/               ← 代理视频
│   ├── semantic_embeddings.npy ← BGE索引 (guest-only)
│   └── tasks/                 ← 任务数据
│
└── vibecap.db                 ← SQLite (不提交git)
```

## 启动

```bash
# 后端
cd vibecap-server
/opt/anaconda3/bin/python3 server.py --project 杨老师教育 --task 0801新东方低价课策略 --port 8765

# 前端
cd vibecap-web && npm run dev
```

## 后端 API

| 端点 | 说明 |
|---|---|
| GET /search?q=&mode=semantic | BGE语义搜索 (口播: guest-only索引) |
| GET /segments.json?task= | 任务分段 (DB优先, 文件fallback) |
| POST /script/generate_script_stream | v3搜索流水线 SSE |
| POST /script/generate_story_first | v4故事优先 SSE |
| GET /proxies/manifest | 代理视频清单 |
| GET /status | 健康检查 |

## 前端路由

- `/` — 任务台 (Home)
- `/:project/:task/planning` — 策划台 (PlanningDesk)
- `/:project/:task/vibe` — 沉浸剪辑台 (VibeEdit)
- `/data` — 数据台 (DataDesk)

## 数据流

```
电视剧: ASR+VLM → cross_calibrate → clean → build_index → BGE搜索 → 剪辑台
口播:   ASR → classify → segment → clean_interview → build_index → story_first → 剪辑台
```

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy, faster-whisper)
- DeepSeek API: DEEPSEEK_API_KEY (策划台LLM + 数据台清洗)
- MiMo API: MIMO_API_KEY (VLM画面分析, 仅电视剧)
- ffmpeg: 视频处理 + 代理生成
- Node: Vite + React 前端
