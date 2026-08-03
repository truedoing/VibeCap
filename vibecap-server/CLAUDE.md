---
name: vibecap-server
description: VIBECAP Python 后端 — 统一数据管线 + 策划台AI + BGE索引
---

## VIBECAP Server v0.11

### 架构
```
vibecap-server/
├── server.py                  ← 主服务 (8765): API + SSE + 静态文件
├── db.py                      ← SQLite: dramas/episodes/tasks/task_segments/index_entries
├── script_agents.py           ← 策划台 AI Agent
│   ├── run_pipeline()         ← v3 搜索流水线 (策划→BGE搜索→压缩→审核)
│   └── story_first_pipeline() ← v4 故事优先 (LLM通读→分组段落)
├── build_index.py             ← BGE索引统一入口 (--project, 自动识别drama/interview)
├── clean_interview_data.py    ← 口播Phase A: LLM清洗文本 + 说话人识别
├── build_interview_index.py   ← 口播Phase B: guest-only + speaker边界 BGE索引
├── classify_transcript.py     ← 口播: LLM ASR四层分类 (content/guide/meta/filler)
├── segment_transcript.py      ← 口播: LLM采样 + 主题分段
├── generate_proxies.py        ← 540p代理视频生成
├── analyze_episodes.py        ← 电视剧: 场景切分+ASR+VLM
├── cross_calibrate.py         ← 电视剧: ASR↔VLM交叉校准
├── clean_data.py              ← 电视剧: 数据清洗+场景合并
└── export_capcut.py           ← 剪映草稿导出
```

### 启动
```bash
# 口播项目
python3 server.py --project 杨老师教育 --task 0801新东方低价课策略 --port 8765

# 电视剧项目
python3 server.py --drama 都挺好 --task Task7029 --port 8765
```

### 核心API

| 端点 | 方法 | 说明 |
|---|---|---|
| /search?q=&mode=semantic | GET | BGE语义搜索 (自动适配VLM有无) |
| /segments.json?task= | GET | 任务分段 (DB→文件fallback) |
| /script/generate_script_stream | POST | v3搜索流水线 SSE |
| /script/generate_story_first | POST | v4故事优先 SSE (口播专用) |
| /proxies/manifest | GET | 代理视频清单 |
| /tasks/create | POST | 创建任务+处理素材 |

### 数据管线

**口播采访 (interview):**
```
ASR → classify_transcript → segment_transcript → clean_interview_data → build_index
         (LLM分类)            (LLM分段)            (清洗+说话人)          (BGE)
```

**电视剧 (drama):**
```
540p代理 → analyze_episodes → cross_calibrate → clean_data → build_index
              (ASR+VLM)         (交叉校准)        (清洗合并)    (BGE)
```

### 数据库 (SQLite)

- `dramas`: 项目注册
- `episodes`: 每集元数据 (ASR/VLM质量分)
- `index_entries`: BGE索引条目
- `tasks` + `task_segments`: 任务和分段 (v0.11: source_start/end/section_role/note)

### 关键依赖
- Python 3.12 (`/opt/anaconda3/bin/python3`)
- sentence-transformers (BGE, HF_HUB_OFFLINE=1)
- DeepSeek API (策划台 + 数据清洗)
- MiMo API (VLM, 仅电视剧)
