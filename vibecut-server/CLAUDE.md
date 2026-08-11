---
name: vibecut-server
description: VibeCut Python 后端 — FastAPI + 模块化架构 + BGE索引 + AI流水线 v1.2
---

## VibeCut Server v1.2

### 架构
```
vibecut-server/
├── main.py                     ← FastAPI 入口 + 路由注册 + 生命周期 (847行)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析 (94行)
├── db.py                       ← SQLite: dramas/episodes/tasks/task_segments/index_entries
│
├── handlers/
│   ├── search.py               ← BGE语义搜索 + ASR关键词/锚定搜索 (485行)
│   ├── tasks.py                ← 任务 CRUD (创建/状态/删除/列表)
│   ├── dialogue.py             ← 对话匹配 + AI聊天 (184行)
│   ├── storyboard.py           ← 导演Agent v8.5: PRIMARY+SECONDARY 分镜 (581行)
│   ├── script_gen.py           ← AI脚本生成 (v3流水线/v4故事优先/精切 SSE)
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/片段提取/预览/导出)
│   ├── static.py               ← SPA前端回退 + 任务目录文件服务
│   └── prompts/
│       └── director.py         ← DIRECTOR_PROMPT 模板 (150行)
│
├── lib/
│   ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo/DeepSeek)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← 可复用SSE发射器 + 心跳
│   ├── env.py                  ← 统一.env加载
│   ├── vlm_cache.py            ← VLM 场景缓存懒加载 (111行)
│   ├── storyboard_match.py     ← 分镜匹配引擎 — 多维度结构化评分 (195行)
│   └── scene_map.py            ← 场记Agent: scene_map + synopsis 生成 (198行)
│
├── script_agents.py            ← 编剧台 AI Agent
│   ├── run_pipeline()          ← v3 搜索流水线
│   └── story_first_pipeline()  ← v4 故事优先 (口播专用)
├── refine_segments.py          ← 口播精切引擎
├── build_index.py              ← BGE索引统一入口 (--project)
├── clean_interview_data.py     ← 口播: LLM清洗+说话人识别
├── classify_transcript.py      ← 口播: LLM ASR分类
├── export_capcut.py            ← 剪映草稿导出
├── generate_proxies.py         ← 540p代理视频
├── analyze_episodes.py         ← 电视剧: 场景+ASR+VLM
├── cross_calibrate.py          ← 电视剧: ASR↔VLM校准 (已废弃)
├── vlm_char_calibrate.py       ← 电视剧: VLM人物校准 (字幕称呼词 + 场景连续性)
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

### 电视剧数据管线 (v1.3 优化后)

```
源视频 → analyze_episodes → VLM 场景分析 (vlm_analysis.json)
    │         (场景+ASR+VLM)         │
    │         v1.3优化:               │
    │         · 角色参考照锚定         │
    │         · 面部优先→反推场景      │
    │         · 剧集概要注入           │
    │         · 上下文窗口传递人物      │
    │         · 跳过序幕/落幕          │
    │                                │
    │                                ▼
    │                         clean_data.py
    │                         数据清洗 + 场景合并
    │                         (sources_clean/epN/)
    │                                │
    │                                ▼
    └─────────────────────── build_index.py
                            BGE 语义索引
                            (31498 条, 768维)
```

**v1.3 新增**:
- VLM分析提示词优化: 角色参考照 + 面部识别优先 + 剧集概要
- 淘汰 cross_calibrate.py (ASR↔VLM校准)
- 淘汰 vlm_char_calibrate.py (T1-T4校准) — VLM源头已解决人物识别问题
- 淘汰 T4 LLM校准 (DeepSeek) — 不再需要

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
- Moonshot API (编剧台LLM + 数据清洗)
- MiMo API (VLM, 仅电视剧)
- MPS (Apple Silicon GPU, 6.8GB VRAM)

### VLM 画面分析策略 (analyze_episodes.py v1.3)

**核心优化**:

1. **角色参考照锚定**: 从 `character_portraits/` 加载角色肖像照，每10场景发送一次作为面孔对比参考
2. **面部优先识别**: prompt 明确要求"先对比面孔与参考照→再反推场景地点"，**严禁先判地点再反推人物**
3. **剧集概要注入**: 通过 DeepSeek 生成每集剧情概要(ep_synopsis.json)，VLM 分析时注入 prompt，提供剧情上下文
4. **上下文窗口**: 串行分析时，前场景的VLM结果（人物+字幕）传递给当前场景，维持对话连贯性
5. **跳过序幕/落幕**: 跳过前1分钟(6场景)片头和后3分钟(18场景)片尾

**精度提升路径**: 原始VLM(苏大强+苏明成) → +角色照(苏明哲+苏明成) → +面孔优先(吴非+苏明哲) ✅

**速度优化**:
- 15s/场景切分，每场景1-2帧
- 分组并发：10场景一组，组内串行(继承上下文)，多组并发(最多4组)
- 每10场景发送一次角色照锚定，中间场景仅依赖上下文
- 预计 25-30 分钟/集

**依赖**: `.env` 中 `MIMO_API_KEY` + `DEEPSEEK_API_KEY` (仅生成剧集概要)

### 分镜搜索策略 (导演Agent v8.5)

**核心思路**: LLM 是导演，将解说词拆解为叙事节拍（beats），运用六种导演手法（REACTION/FLASHBACK/CONTRAST/CUTAWAY/ARC/CROSS），通过多维度结构化匹配引擎找到最优画面。

**关键模块**:
- `handlers/storyboard.py` — 导演Agent 入口: LLM叙事分析 + PRIMARY/SECONDARY 分镜匹配
- `lib/storyboard_match.py` — 纯函数匹配引擎 (多维度评分, 独立可测试)
- `lib/vlm_cache.py` — 46集 VLM 场景缓存懒加载
- `lib/scene_map.py` — 场记Agent: DeepSeek生成 scene_map + synopsis
- `handlers/prompts/director.py` — DIRECTOR_PROMPT 模板

**评分维度**: 剧集锚定(三层权重) + 人物精确匹配 + 场景情绪冲突补偿(v8.5) + 情绪关键词 + 强度 + 景别距离补偿 + 地点模糊匹配 + 动作滑窗匹配

**台词定位**: `dialogue_match` 第一句锚定 ASR (2-4字滑窗 + cluster scoring, 0ms 延迟)
