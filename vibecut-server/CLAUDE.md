---
name: vibecut-server
description: VibeCut Python 后端 — FastAPI + 模块化架构 + BGE索引 + AI流水线
---

## VibeCut Server v1.1 (重构后)

### 架构
```
vibecut-server/
├── main.py                     ← FastAPI 入口 + 路由注册 + 生命周期 (805行)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析 (94行)
├── db.py                       ← SQLite: dramas/episodes/tasks/task_segments/index_entries
│
├── handlers/
│   ├── search.py               ← 6种搜索引擎 (语义/关键词/混合/ASR优先/深度/口播)
│   ├── tasks.py                ← 任务 CRUD (创建/状态/删除/列表)
│   ├── script_gen.py           ← AI脚本生成 (v3流水线/v4故事优先/精切 SSE)
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/片段提取/预览/导出)
│   ├── dialogue.py             ← 对话+台词 (chat/dialogue_match/storyboard)
│   └── static.py               ← SPA前端回退 + 任务目录文件服务
│
├── lib/
│   ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo, 消除10种重复)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← 可复用SSE发射器 + 心跳
│   └── env.py                  ← 统一.env加载
│
├── script_agents.py            ← 策划台 AI Agent
│   ├── run_pipeline()          ← v3 搜索流水线
│   └── story_first_pipeline()  ← v4 故事优先 (口播专用)
├── refine_segments.py          ← 口播精切引擎
├── build_index.py              ← BGE索引统一入口 (--project)
├── clean_interview_data.py     ← 口播: LLM清洗+说话人识别
├── classify_transcript.py      ← 口播: LLM ASR分类
├── export_capcut.py            ← 剪映草稿导出
├── generate_proxies.py         ← 540p代理视频
├── analyze_episodes.py         ← 电视剧: 场景+ASR+VLM
├── cross_calibrate.py          ← 电视剧: ASR↔VLM校准
├── clean_data.py               ← 电视剧: 数据清洗
└── ...                         ← 其他独立脚本
```

### 启动

```bash
cd vibecut-server

# FastAPI (推荐, v1.1)
/opt/anaconda3/bin/python3 main.py --project 杨老师教育 --task 0801学习新东方 --port 8765

# 兼容旧版 (server.py 仍然可用, 但功能冻结)
/opt/anaconda3/bin/python3 server.py --project 杨老师教育 --task 0801学习新东方 --port 8765
```

### 核心API

| 端点 | 方法 | 说明 |
|---|---|---|
| /status | GET | 健康检查 (项目/类型/版本) |
| /search?q=&mode=semantic | GET | BGE语义搜索 (自动适配drama/interview) |
| /segments.json?task= | GET | 任务分段 (DB→文件fallback) |
| /dramas | GET | 项目列表 |
| /tasks?drama= | GET | 任务列表 |
| /tasks/create | POST | 创建任务 (JSON或multipart) |
| /tasks/status | POST | 更新任务状态 |
| /tasks/delete | POST | 删除任务 |
| /script/generate_script | POST | v3 三步混编 (JSON响应) |
| /script/generate_script_stream | POST | v3 搜索流水线 SSE |
| /script/generate_story_first | POST | v4 故事优先 SSE (口播专用) |
| /script/refine | POST | 精切 SSE |
| /script/analyze_transcript | POST | LLM 转写分析 |
| /script/generate_from_outline | POST | 大纲→segments |
| /chat | POST | 对话式素材搜索 |
| /dialogue_match | POST | 台词拆解+ASR匹配 |
| /storyboard_suggest | POST | 分镜推荐 |
| /assign | POST | 确认素材片段 |
| /copy | POST | 复制预览文件 |
| /proxies/manifest | GET | 代理视频清单 |
| /proxies/{filename} | GET | 代理视频 (Range) |
| /clips/{path}?task= | GET | 任务目录片段 (Range) |
| /asr/raw?project= | GET | 原始ASR文本 |
| /asr/classified?project= | GET | LLM分类后的ASR |
| /data/process | POST | 启动后台加工流水线 |
| /data/status?task_id= | GET | 流水线进度 |
| /export/extract_clips | POST | 批量提取高清片段 |
| /picks | POST | 同步picks到SQLite |
| /{filename}?task= | GET | 任务目录文件 (SPA兜底) |

### 口播数据管线

```
ASR → classify_transcript → clean_interview_data → build_index
       (LLM四层分类)         (清洗+说话人)          (BGE)
                                                       ↓
                                               story_first (粗段)
                                                       ↓
                                               POST /script/refine
                                               refine_segments.py
                                               (精切: sub_clips KEEP/CUT)
                                                       ↓
                                               export_capcut.py
                                               (剪映草稿, CUT音量=5%)
```

### 目录约定

- 项目数据: `<BASE_DIR>/<项目名>/` (sources/, sources_clean/, proxies/, tasks/)
- 项目配置: `projects/<项目名>.json`
- 数据库: `<BASE_DIR>/vibecut.db`
- 前端构建: `../vibecut-web/dist/`

### 依赖

- Python 3.12 (`/opt/anaconda3/bin/python3`)
- FastAPI + Uvicorn (conda install)
- sentence-transformers (BGE, HF_HUB_OFFLINE=1)
- Moonshot API (策划台 + 数据清洗)
- MiMo API (VLM, 仅电视剧)
