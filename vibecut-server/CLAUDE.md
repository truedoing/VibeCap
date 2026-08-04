---
name: vibecut-server
description: VibeCut Python 后端 — 统一数据管线 + 策划台AI + 精切引擎 + BGE索引
---

## VibeCut Server v1.0

### 架构
```
vibecut-server/
├── server.py                  ← 主服务 (8765): API + SSE + 静态文件
├── db.py                      ← SQLite: dramas/episodes/tasks/task_segments/index_entries
├── script_agents.py           ← 策划台 AI Agent
│   ├── run_pipeline()         ← v3 搜索流水线 (策划→BGE搜索→压缩→审核)
│   └── story_first_pipeline() ← v4 故事优先 (LLM通读→分组段落)
├── refine_segments.py         ← 口播精切引擎 (v0.12新增)
│   └── refine()               ← 粗段 + classified_enhanced → sub_clips KEEP/CUT
├── build_index.py             ← BGE索引统一入口 (--project, 自动识别drama/interview)
├── clean_interview_data.py    ← 口播Phase A: LLM清洗文本 + 说话人识别
├── classify_transcript.py     ← 口播: LLM ASR四层分类 (content/guide/meta/filler)
├── export_capcut.py           ← 剪映草稿导出 (v0.12: 支持sub_clips精切粒度)
├── generate_proxies.py        ← 540p代理视频生成
├── analyze_episodes.py        ← 电视剧: 场景切分+ASR+VLM
├── cross_calibrate.py         ← 电视剧: ASR↔VLM交叉校准
├── clean_data.py              ← 电视剧: 数据清洗+场景合并
└── export_capcut.py           ← 剪映草稿导出
```

### 启动
```bash
# 口播项目
python3 server.py --project 杨老师教育 --task 0801学习新东方 --port 8765

# 电视剧项目
python3 server.py --drama 都挺好 --task Task7029 --port 8765
```

### 核心API

| 端点 | 方法 | 说明 |
|---|---|---|
| /search?q=&mode=semantic | GET | BGE语义搜索 (自动适配VLM有无) |
| /segments.json?task= | GET | 任务分段 (DB→文件fallback, DB空时fallthrough到文件) |
| /script/generate_script_stream | POST | v3搜索流水线 SSE |
| /script/generate_story_first | POST | v4故事优先 SSE (口播专用) |
| /script/refine | POST | 精切 SSE (v0.12新增) |
| /proxies/manifest | GET | 代理视频清单 (.proxies_manifest.json) |
| /tasks/文案脚本.json | GET | 文案脚本 (任务级→项目级fallback) |
| /picks | POST | 同步picks到SQLite |

### 口播数据管线 (v0.12)

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

### 数据库 (SQLite)

- `dramas`: 项目注册
- `episodes`: 每集元数据 (ASR/VLM质量分)
- `index_entries`: BGE索引条目
- `tasks` + `task_segments`: 任务和分段 (sub_clips存文件, DB为辅助)

### segments.json 结构 (v0.12)

```json
{
  "segments": [{
    "seg_id": 0, "source_start": 2.5, "source_end": 16.9,
    "sub_clips": [
      {"start": 2.5, "end": 6.2, "text": "...", "decision": "KEEP", "speaker": "guest"},
      {"start": 6.2, "end": 8.7, "text": "...", "decision": "CUT", "speaker": "host"}
    ],
    "refine_stats": {"keep": 2, "cut": 1, "keep_duration": 12.0, "cut_duration": 2.5}
  }],
  "refined": true,
  "refine_summary": {"keep": 22, "cut": 10, "keep_duration": 168.2, "cut_duration": 11.1}
}
```

### 关键依赖
- Python 3.12 (`/opt/anaconda3/bin/python3`)
- sentence-transformers (BGE, HF_HUB_OFFLINE=1)
- DeepSeek API (策划台 + 数据清洗)
- MiMo API (VLM, 仅电视剧)
