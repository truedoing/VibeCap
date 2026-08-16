---
name: vibecut-server
description: VibeCut Python 后端 — FastAPI + 模块化架构 + BGE索引 + VLM流水线 + MiMo配音 v1.4
---

## VibeCut Server v1.4

### 架构
```
vibecut-server/
├── main.py                     ← FastAPI 入口 (瘦入口, 路由分发到 routers/)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析
├── db.py                       ← SQLite: dramas/tasks/task_segments/index_entries
│
├── routers/                    ← API 路由 (按功能域拆分)
│   ├── _lifespan.py            ← 启动生命周期: 索引加载
│   ├── search.py               ← GET /status, /search
│   ├── task_crud.py            ← GET /dramas, /tasks + POST /tasks/*
│   ├── segments.py             ← GET /segments.json, /narration.json + 外部导入
│   ├── asr.py                  ← GET /asr/raw, /asr/classified
│   ├── media.py                ← GET /proxies/*, /clips/*, /tts_segments/*, /posters/*
│   ├── ai.py                   ← POST /storyboard_suggest
│   ├── sse_script.py           ← SSE: /script/generate_drama_script_v2
│   ├── sse_voiceover.py        ← /voiceover/voices, /create_voice, /generate_stream, /regenerate_segment
│   ├── pipeline.py             ← GET/POST /data/*
│   ├── export.py               ← POST /export/extract_clips
│   ├── picks.py                ← POST /picks
│   └── static.py               ← GET /{filename} SPA fallback
│
├── handlers/                   ← 业务逻辑
│   ├── search.py               ← BGE语义搜索
│   ├── tasks.py                ← 任务 CRUD
│   ├── storyboard.py           ← 导演Agent v8.5: PRIMARY+SECONDARY 分镜
│   ├── script_drama.py         ← drama 脚本生成 v2 (单 LLM)
│   ├── voiceover.py            ← 配音: 规则方案 + MiMo TTS
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/导出/文件服务)
│   ├── static.py               ← SPA前端回退 + 任务目录文件服务
│   └── prompts/
│       ├── director.py         ← DIRECTOR_PROMPT 模板
│       └── script_drama.py     ← SCRIPT_V2_PROMPT 模板
│
├── cli/                        ← CLI 脚本 (数据管线 + 任务工具)
│   ├── analyze_episodes.py     ← VLM 三层推理 (DeepSeek→ASR→VLM)
│   ├── build_index.py          ← BGE索引统一入口
│   ├── migrate_db.py           ← 导入数据库
│   ├── cross_calibrate.py      ← 交叉校准
│   ├── clean_data.py           ← 数据清洗
│   ├── classify_transcript.py  ← 口播 ASR 分类
│   ├── clean_interview_data.py ← 口播清洗
│   ├── segment_transcript.py   ← 口播主题分段
│   ├── parse_docx.py           ← docx 解析
│   ├── parse_external_json.py  ← 外部 JSON 归一化
│   ├── asr_narration.py        ← 解说音频 ASR
│   ├── match_split.py          ← 文案↔ASR 对齐切分
│   └── generate_proxies.py     ← 代理视频生成
│
├── lib/                        ← 公共库
│   ├── llm.py                  ← 统一LLM调用 (DeepSeek/Moonshot)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← SSE 流式生成器 + make_emitter
│   ├── env.py                  ← 统一.env加载
│   ├── vlm_cache.py            ← VLM 场景缓存懒加载
│   ├── storyboard_match.py     ← 分镜匹配引擎
│   ├── scene_map.py            ← 场记Agent: scene_map + synopsis
│   ├── voice_store.py          ← 全局音色库 (预设+克隆)
│   └── segments_store.py       ← segments 加载/落盘 helper
│
└── tts_engine.py               ← MiMo API TTS (预设音色 + voiceclone)
```

### 启动

```bash
cd vibecut-server
/opt/anaconda3/bin/python3 main.py --project 都挺好 --task Task7024 --port 8765
```

### 核心API

| 端点 | 方法 | 说明 |
|---|---|---|
| /status | GET | 健康检查 (项目/类型/版本) |
| /search?q=&mode=semantic | GET | BGE语义搜索 (drama/interview) |
| /segments.json?task= | GET | 任务分段 (DB→文件fallback) |
| /dramas | GET | 项目列表 |
| /tasks?drama= | GET | 任务列表 |
| /tasks/create | POST | 创建任务 (docx/音频上传) |
| /tasks/status | POST | 更新任务状态 |
| /tasks/delete | POST | 删除任务 |
| /script/import_external_json | POST | 外部解说 JSON 导入 (扣子/WorkBuddy) |
| /script/generate_drama_script_v2 | POST | drama 脚本生成 v2 (单 LLM) SSE |
| /voiceover/voices | GET | 音色列表 (预设 + 克隆) |
| /voiceover/create_voice | POST | 新建克隆音色 (上传参考音频) |
| /voiceover/generate_stream | POST | 一键全量配音 SSE |
| /voiceover/regenerate_segment | POST | 单段配音 SSE |
| /storyboard_suggest | POST | 分镜推荐 |
| /proxies/manifest | GET | 代理视频清单 |
| /proxies/{filename} | GET | 代理视频 (Range) |
| /clips/{path}?task= | GET | 任务目录片段 (Range) |
| /tts_segments/{file}?task= | GET | 配音音频 |
| /asr/raw?project= | GET | 原始ASR文本 |
| /asr/classified?project= | GET | LLM分类后的ASR |
| /data/process | POST | 启动后台加工流水线 |
| /data/process_status?task_id= | GET | 流水线进度 |
| /data/quality?project= | GET | 每集数据质量 (ASR+VLM+scene_map+概要) |
| /export/extract_clips | POST | 批量提取高清片段 |
| /picks | POST | 同步picks到SQLite |
| /{filename}?task= | GET | 任务目录文件 (SPA兜底) |

### 脚本生成 — Drama v2 (单 LLM + 方法论)

**范式**: 放弃多 Agent 协作，单 LLM 一次产出完整脚本。公网 LLM 对老流行剧的知识比自建 ASR 更可靠。

```
选题 → DeepSeek(SCRIPT_V2_PROMPT) → 完整脚本(论点+装置+起承转合+名场面function) → 落盘 segments.json
```

**API**: `POST /script/generate_drama_script_v2`
```json
{"topic": "苏大强与保姆小蔡：保姆三句话，骗走一套房", "target_duration": 300}
```

### 配音 — 规则驱动 + MiMo TTS

```
选中段(narration_text) → 规则方案(narrative + 1.0x) → MiMo TTS → narr_{seg_id:03d}.wav
```

- 预设音色：冰糖/茉莉/苏打/白桦
- 克隆音色：上传参考音频 → MiMo voiceclone → 全局共享 (voices/)
- 产物：narration.json + tts_meta.json + segments.json 反写 audio_duration

### 电视剧数据管线 (v3.1)

```
源视频 → analyze_episodes → VLM 场景分析 (vlm_seg_cache_v3.json)
    │         (场景+ASR+VLM)         │
    │                                ▼
    │                         scene_map.json (46集1511场景, 100%完整)
    │                                │
    └─────────────────────── build_index.py
                            BGE 语义索引 (29854条, 768维)
```

### 依赖

- Python 3.12 (`/opt/anaconda3/bin/python3`)
- FastAPI + Uvicorn
- sentence-transformers (BGE, HF_HUB_OFFLINE=1)
- DeepSeek API (脚本生成 + scene_map + 分镜推荐)
- MiMo API (MIMO_API_KEY: VLM, MIMO_TTS_API_KEY: TTS)
- MPS (Apple Silicon GPU, 6.8GB VRAM)

### 分镜搜索策略 (导演Agent v8.5)

**核心思路**: LLM 是导演，将解说词拆解为叙事节拍（beats），通过多维度结构化匹配引擎找到最优画面。

**关键模块**:
- `handlers/storyboard.py` — 导演Agent 入口: LLM叙事分析 + PRIMARY/SECONDARY 分镜匹配
- `lib/storyboard_match.py` — 纯函数匹配引擎 (多维度评分, 独立可测试)
- `lib/vlm_cache.py` — 46集 VLM 场景缓存懒加载
- `lib/scene_map.py` — 场记Agent: DeepSeek生成 scene_map + synopsis
- `handlers/prompts/director.py` — DIRECTOR_PROMPT 模板

**评分维度**: 剧集锚定(三层权重) + 人物精确匹配 + 场景情绪冲突补偿(v8.5) + 情绪关键词 + 强度 + 景别距离补偿 + 地点模糊匹配 + 动作滑窗匹配
