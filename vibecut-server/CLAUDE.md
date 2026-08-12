---
name: vibecut-server
description: VibeCut Python 后端 — FastAPI + 模块化架构 + BGE索引 + AI流水线 v1.3
---

## VibeCut Server v1.3

### 架构
```
vibecut-server/
├── main.py                     ← FastAPI 入口 (50行瘦入口, 路由分发到 routers/)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析 (94行)
├── db.py                       ← SQLite: dramas/episodes/tasks/task_segments/index_entries
│
├── routers/                    ← API 路由 (v1.3 新增, 按功能域拆分)
│   ├── _lifespan.py            ← 启动生命周期: 索引加载 + BGE预热 + Agent注入
│   ├── search.py               ← GET /status, /search
│   ├── task_crud.py            ← GET /dramas, /tasks + POST /tasks/* (两个router)
│   ├── segments.py             ← GET /segments.json, /narration.json
│   ├── asr.py                  ← GET /asr/raw, /asr/classified
│   ├── media.py                ← GET /proxies/*, /clips/*, /posters/*; POST 剪辑操作
│   ├── ai.py                   ← POST /chat, /dialogue_match, /storyboard_suggest, /script/*
│   ├── sse_script.py           ← SSE: /script/generate_script_stream, /refine, /generate_drama_script
│   ├── sse_voiceover.py        ← SSE: /voiceover/generate_stream (配音台)
│   ├── pipeline.py             ← GET/POST /data/*
│   ├── export.py               ← POST /export/extract_clips
│   ├── picks.py                ← POST /picks
│   └── static.py               ← GET /{filename} SPA fallback
│
├── handlers/                   ← 业务逻辑 (不变)
│   ├── search.py               ← BGE语义搜索 + ASR关键词/锚定搜索 (485行)
│   ├── tasks.py                ← 任务 CRUD (创建/状态/删除/列表, 支持无docx创建)
│   ├── dialogue.py             ← 对话匹配 + AI聊天 (184行)
│   ├── storyboard.py           ← 导演Agent v8.5: PRIMARY+SECONDARY 分镜 (581行)
│   ├── script_gen.py           ← interview AI脚本生成 (v3流水线/v4故事优先/精切 SSE)
│   ├── script_drama.py         ← drama AI脚本生成 SSE handler
│   ├── voiceover.py            ← 配音台: 配音师Agent + TTS生成
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/片段提取/预览/导出)
│   ├── static.py               ← SPA前端回退 + 任务目录文件服务
│   └── prompts/
│       ├── director.py         ← DIRECTOR_PROMPT 模板
│       ├── script_drama.py     ← 编剧Agent Prompt (故事师/策划师/文案师)
│       └── voiceover.py        ← 配音师 Prompt 模板
│
├── agents/                     ← AI Agent 模块 (v1.3 从根目录提升)
│   ├── script_agents.py        ← interview编剧台 (1045行)
│   └── drama_script_agents.py  ← drama编剧台 (604行)
│
├── cli/                        ← CLI 脚本 (v1.3 从根目录移入, 24个)
│   ├── build_index.py          ← BGE索引统一入口
│   ├── analyze_episodes.py     ← 电视剧: 场景+ASR+VLM
│   ├── refine_segments.py      ← 口播精切引擎
│   ├── match_split.py          ← 文本对齐+音频分割
│   └── ...                     ← 其他独立脚本
│
├── lib/                        ← 公共库
│   ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo/DeepSeek)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← 通用 SSE 流式生成器 + 心跳
│   ├── env.py                  ← 统一.env加载
│   ├── vlm_cache.py            ← VLM 场景缓存懒加载
│   ├── storyboard_match.py     ← 分镜匹配引擎
│   └── scene_map.py            ← 场记Agent: scene_map + synopsis生成
│
├── tts_engine.py               ← 统一 TTS 引擎 (MiMo API)
└── export_capcut.py            ← 剪映草稿导出
```

### 启动

```bash
cd vibecut-server
/opt/anaconda3/bin/python3 main.py --project 都挺好 --task Task0804 --port 8765
```

### 核心API

| 端点 | 方法 | 说明 |
|---|---|---|
| /status | GET | 健康检查 (项目/类型/版本) |
| /search?q=&mode=semantic | GET | BGE语义搜索 (自动适配drama/interview) |
| /segments.json?task= | GET | 任务分段 (DB→文件fallback) |
| /dramas | GET | 项目列表 |
| /tasks?drama= | GET | 任务列表 |
| /tasks/create | POST | 创建任务 (支持无docx, AI编剧模式) |
| /tasks/create_json | POST | 创建任务 JSON (无需上传文件) |
| /tasks/status | POST | 更新任务状态 |
| /tasks/delete | POST | 删除任务 |
| /script/generate_script | POST | v3 三步混编 (JSON响应) |
| /script/generate_script_stream | POST | v3 搜索流水线 SSE |
| /script/generate_story_first | POST | v4 故事优先 SSE (interview) |
| /script/generate_drama_script | POST | **v1 编剧Agent SSE (drama) — 新 v1.2** |
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
| /data/quality?project= | GET | 每集数据质量 (ASR+VLM+scene_map+概要) |
| /export/extract_clips | POST | 批量提取高清片段 |
| /picks | POST | 同步picks到SQLite |
| /{filename}?task= | GET | 任务目录文件 (SPA兜底) |

### 编剧Agent v1 — Drama脚本生成 (新 v1.2)

**核心理念**: 三个独立Agent角色协作，人提供创意方向（选题+选集+时长），Agent负责执行。

```
选题+选集+时长 → 故事师(全剧概要→故事地图) → 策划师(故事地图→章节方案)
                                                    │
                                                    ▼
                                          文案师(章节+scene_map→解说词+scene_query)
                                                    │
                                                    ▼
                                          程序校验(scene_query↔scene_map一致性)
                                                    │
                                                    ▼
                                          segments.json (含episode_marker+source_start/end)
```

**7层写作结构**: 核心视角 / 开场钩子(≤50字) / 原剧台词 / 解说节奏 / 语言风格(网感) / 人物心理 / 结尾金句

**审核**: 程序校验替代LLM审核 (scene_query与scene_map精确匹配，0 LLM调用，节省~70s)

**API**: `POST /script/generate_drama_script`
```json
{"topic": "苏明成人物线", "episodes": [1,3,21,39,41,45], "target_duration": 240}
```

### 电视剧数据管线 (v3.1)

```
源视频 → analyze_episodes → VLM 场景分析 (vlm_seg_cache_v3.json)
    │         (场景+ASR+VLM)         │
    │                                ▼
    │                         scene_map.json (46集1511场景, 100%完整)
    │                                │
    │                                ▼
    └─────────────────────── build_index.py
                            BGE 语义索引 (29854条, 768维)
```

**scene_map 质量**: 46集共1511个场景，event/mood/location/characters 完整率 100%

### 依赖

- Python 3.12 (`/opt/anaconda3/bin/python3`)
- FastAPI + Uvicorn
- sentence-transformers (BGE, HF_HUB_OFFLINE=1)
- DeepSeek API (编剧Agent + scene_map生成)
- Moonshot API (interview编剧台LLM)
- MiMo API (VLM, 仅电视剧)
- MPS (Apple Silicon GPU, 6.8GB VRAM)

### 分镜搜索策略 (导演Agent v8.5)

**核心思路**: LLM 是导演，将解说词拆解为叙事节拍（beats），运用六种导演手法（REACTION/FLASHBACK/CONTRAST/CUTAWAY/ARC/CROSS），通过多维度结构化匹配引擎找到最优画面。

**关键模块**:
- `handlers/storyboard.py` — 导演Agent 入口: LLM叙事分析 + PRIMARY/SECONDARY 分镜匹配
- `lib/storyboard_match.py` — 纯函数匹配引擎 (多维度评分, 独立可测试)
- `lib/vlm_cache.py` — 46集 VLM 场景缓存懒加载
- `lib/scene_map.py` — 场记Agent: DeepSeek生成 scene_map + synopsis
- `handlers/prompts/director.py` — DIRECTOR_PROMPT 模板

**评分维度**: 剧集锚定(三层权重) + 人物精确匹配 + 场景情绪冲突补偿(v8.5) + 情绪关键词 + 强度 + 景别距离补偿 + 地点模糊匹配 + 动作滑窗匹配
