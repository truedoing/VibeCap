# VibeCut — AI 影视解说导演台

对原剧进行 VLM 画面分析 + ASR 台词转写，构建 BGE 语义索引，然后根据解说词自动搜索匹配原剧镜头，完成解说短视频的分镜与导出。定位为"导演台"——在 VibeCut 完成创作决策（写词 + 分镜），导出到剪映做技术性剪辑。

## 工作流

```
解说词 → LLM 分镜 → BGE 搜索匹配画面 → 选取镜头 → 时间轴编排 → 导出
```

## 四台流水线

```
项目 ──→ 数据台 ──→ 编剧台 ──→ 分镜台 ──→ 剪映
制片      建索引     写解说词    分镜匹配     精剪导出
```

## 项目结构

```
VibeCut/
├── vibecut-server/       ← Python 后端 (FastAPI + Uvicorn, 8765)
│   ├── main.py               ← FastAPI 入口 + 路由注册 (v1.1)
│   ├── config.py             ← CLI参数 + 项目配置 + 路径解析
│   ├── db.py                 ← SQLite 数据库层
│   ├── script_agents.py      ← 编剧台 AI Agent (v3搜索+v4故事优先)
│   ├── refine_segments.py    ← 口播精切引擎
│   ├── lib/                  ← 共享基础设施
│   │   ├── llm.py            ← 统一 LLM 调用 (Moonshot/MiMo)
│   │   ├── embeddings.py     ← BGE 模型单例
│   │   ├── sse.py            ← SSE 发射器 + 心跳
│   │   └── subprocess_runner.py ← 子进程执行器
│   ├── handlers/             ← 接口处理器 (8个模块)
│   │   ├── search.py         ← 6种搜索引擎
│   │   ├── tasks.py          ← 任务 CRUD
│   │   ├── script_gen.py     ← AI脚本生成 (v3/v4/refine SSE)
│   │   ├── pipeline.py       ← 后台加工流水线
│   │   ├── media.py          ← 媒体服务 (代理/片段/导出)
│   │   ├── dialogue.py       ← 对话+台词+分镜推荐
│   │   └── static.py         ← SPA前端回退
│   └── (独立脚本...)
│       ├── analyze_episodes.py   剧集分析 (场景切分/ASR/VLM)
│       ├── build_index.py        构建 BGE 语义索引
│       ├── parse_docx.py         解说文案解析
│       ├── asr_narration.py      解说音频 ASR (faster-whisper)
│       ├── match_split.py        解说词 ↔ ASR 对齐 + 音频切分
│       └── export_capcut.py      剪映草稿导出
│
├── vibecut-web/          ← React 前端 (Vite, 3000)
│   └── src/pages/
│       ├── Home.jsx           项目管理
│       ├── PlanningDesk.jsx   编剧台 (脚本+精切)
│       ├── VibeEdit.jsx       分镜台
│       └── DataDesk.jsx       数据台 (流水线管理)
│
└── {电视剧/口播}/        ← 数据目录 (不提交)
    ├── sources/               ASR + VLM 原始数据
    ├── sources_clean/         清洗后数据 + 分类
    ├── proxies/               540p 代理视频
    ├── tasks/                 剪辑任务
    └── semantic_embeddings.npy BGE 语义索引 (mmap)
```

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:truedoing/VibeCut.git
cd VibeCut

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入:
#   MIMO_API_KEY=sk-xxx        (VLM 画面分析)
#   MOONSHOT_API_KEY=sk-xxx    (DeepSeek LLM 所有功能)

# 3. 安装依赖
cd vibecut-web && npm install && cd ..
conda install fastapi uvicorn
pip install faster-whisper sentence-transformers python-docx numpy

# 4. 准备数据
#   - 原剧视频放入 解说剪辑/都挺好原剧/
#   - 口播视频配置在 projects/<项目名>.json

# 5. 分析剧集 (可选，电视剧需要)
cd vibecut-server
python3 analyze_episodes.py --episodes 1,2,3
python3 build_index.py --project 都挺好

# 6. 启动
cd vibecut-server
python3 main.py --project 杨老师教育 --task 0801学习新东方 --port 8765 &
cd ../vibecut-web && npm run dev
# 打开 http://localhost:3000
# API 文档: http://localhost:8765/docs
```

## 技术栈

| 层 | 技术 | 版本 |
|---|---|---|
| 画面分析 | MiMo VLM (mimo-v2.5) | — |
| 台词转写 | faster-whisper base (本地) | — |
| 语义搜索 | BGE-base-zh-v1.5 (768维) | — |
| LLM 推理 | Moonshot (moonshot-v1-8k) | — |
| 前端 | React + Vite + Tailwind CSS | 19 / 8 / 4 |
| 视频编辑 | Elah (editor + timeline) | 0.3.2 |
| 后端框架 | FastAPI + Uvicorn | 0.112 / 0.35 |
| 数据库 | SQLite (vibecut.db) | — |
| 媒体处理 | ffmpeg + ffprobe | — |

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| /status | GET | 健康检查 (项目/类型/版本) |
| /docs | GET | Swagger 自动文档 |
| /search?q=&mode= | GET | 6 种搜索引擎 (semantic/keyword/hybrid/asr_first/deep) |
| /segments.json?task= | GET | 任务分段 |
| /dramas | GET | 项目列表 |
| /tasks?drama= | GET | 任务列表 |
| /asr/raw | GET | 原始 ASR 文本 |
| /asr/classified | GET | LLM 分类后的 ASR |
| /proxies/manifest | GET | 代理视频清单 |
| /proxies/{filename} | GET | 代理视频 (Range) |
| /clips/{path}?task= | GET | 任务目录片段 |
| /tasks/create | POST | 创建任务 (JSON/multipart) |
| /tasks/status | POST | 更新任务状态 |
| /tasks/delete | POST | 删除任务 |
| /chat | POST | 对话式素材搜索 |
| /dialogue_match | POST | 台词拆解+ASR匹配 |
| /storyboard_suggest | POST | 分镜推荐 |
| /script/generate_script | POST | v3 三步混编 |
| /script/generate_script_stream | POST | v3 搜索流水线 (SSE) |
| /script/generate_story_first | POST | v4 故事优先 (SSE) |
| /script/refine | POST | 精切 (SSE) |
| /script/analyze_transcript | POST | LLM 转写分析 |
| /script/generate_from_outline | POST | 大纲→segments |
| /assign | POST | 确认素材片段 |
| /picks | POST | 同步 picks 到 SQLite |
| /data/process | POST | 启动后台加工流水线 |
| /data/status?task_id= | GET | 流水线进度 |
| /export/extract_clips | POST | 批量提取高清片段 |
