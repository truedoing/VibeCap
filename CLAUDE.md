# VibeCut — AI 影视解说/口播剪辑台 v0.12

## 项目类型

| 类型 | 项目 | 源素材 | 索引方式 |
|---|---|---|---|
| drama | 都挺好 | 46集 1080p | BGE (ASR + VLM) |
| interview | 杨老师教育 | 口播采访 | BGE (ASR, guest-only, speaker边界) |

## 目录

```
VibeCut/
├── vibecut-server/            ← Python 后端 (端口8765)
│   ├── server.py              ← 主服务 + API
│   ├── db.py                  ← SQLite (dramas/episodes/tasks/task_segments/index_entries)
│   ├── script_agents.py       ← 策划台 AI: v3搜索流水线 + v4故事优先
│   ├── refine_segments.py     ← 口播精切引擎: 粗段→sub_clips (KEEP/CUT标注)
│   ├── build_index.py         ← BGE索引统一入口 (--project)
│   ├── clean_interview_data.py← 口播: LLM清洗+说话人识别
│   ├── classify_transcript.py ← 口播: LLM ASR分类
│   ├── export_capcut.py       ← 剪映草稿导出 (支持精切粒度)
│   ├── generate_proxies.py    ← 540p代理视频
│   └── (analyze_episodes/cross_calibrate/clean_data — 电视剧管线)
│
├── vibecut-web/               ← React 前端 (Vite, 端口3000)
│   └── src/
│       ├── pages/
│       │   ├── PlanningDesk.jsx  ← 策划台: 粗剪→精剪→导出
│       │   ├── VibeEdit.jsx      ← 沉浸剪辑台: 自动建轨+精切预览
│       │   ├── DataDesk.jsx      ← 数据台: 流水线管理
│       │   └── Home.jsx          ← 任务台
│       ├── components/
│       │   ├── ScriptPanel.jsx   ← 脚本面板 (精切/粗段自适应)
│       │   ├── ChatPanel.jsx     ← AI搜索面板 (口播/影剧自适应)
│       │   ├── SourceInspector.jsx ← PR风格源检视器
│       │   └── TimelineControls.jsx ← 播放控制栏
│       └── lib/
│           ├── timelineBuilder.js ← Elah项目构建 (interview/drama双模式)
│           └── proxyEngine.js     ← 代理视频解析
│
├── docs/                      ← 文档
├── projects/                  ← 项目配置
│   ├── 都挺好.json
│   └── 杨老师教育.json
│
├── 都挺好/                    ← 电视剧数据
├── 杨老师教育/                ← 口播数据
│   ├── sources/               ← 原始ASR
│   ├── sources_clean/         ← classified / enhanced / segmented
│   ├── proxies/               ← 代理视频 + .proxies_manifest.json
│   ├── semantic_embeddings.npy ← BGE索引 (guest-only)
│   └── tasks/                 ← 任务数据 (segments.json 含 sub_clips)
│
└── vibecut.db                 ← SQLite (不提交git)
```

## 启动

```bash
# 后端
cd vibecut-server
/opt/anaconda3/bin/python3 server.py --project 杨老师教育 --task 0801学习新东方 --port 8765

# 前端
cd vibecut-web && npm run dev
```

## 后端 API

| 端点 | 方法 | 说明 |
|---|---|---|
| GET /search?q=&mode=semantic | GET | BGE语义搜索 (口播: guest-only索引) |
| GET /segments.json?task= | GET | 任务分段 (DB→文件fallback, 含sub_clips) |
| POST /script/generate_script_stream | POST | v3搜索流水线 SSE |
| POST /script/generate_story_first | POST | v4故事优先 SSE (口播专用) |
| POST /script/refine | POST | 精切 SSE — 粗段→sub_clips KEEP/CUT |
| GET /proxies/manifest | GET | 代理视频清单 |
| GET /status | GET | 健康检查 |

## 前端路由

- `/` — 任务台 (Home)
- `/:project/:task/planning` — 策划台 (PlanningDesk)
- `/:project/:task/vibe` — 沉浸剪辑台 (VibeEdit)
- `/data` — 数据台 (DataDesk)

## 口播工作流 (v0.12)

```
策划台:
  ASR → content report → 输入主题 → 🧠 AI生成脚本 (粗剪14段)
  → 审核粗段脚本 → ✂️ 精剪 (refine) → sub_clips 22K+10C
  → 粗剪/精切 页签切换审核 → 导出 CapCut

剪辑台:
  打开 → 口播自动建轨 (仅KEEP sub_clips → 时间轴)
  → 精切预览 (左面板 绿✅/红❌) → 微调

导出:
  segments.json (含sub_clips) → export_capcut.py → 剪映草稿
  CUT项音量=5% 便于识别删除
```

## 数据流

```
口播: ASR → classify → clean_interview → build_index → story_first → refine → 剪辑台/CapCut
电视剧: ASR+VLM → cross_calibrate → clean → build_index → BGE搜索 → 剪辑台
```

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy, faster-whisper)
- DeepSeek API: DEEPSEEK_API_KEY (策划台LLM + 数据台清洗)
- MiMo API: MIMO_API_KEY (VLM画面分析, 仅电视剧)
- ffmpeg: 视频处理 + 代理生成
- Node: Vite + React 前端
