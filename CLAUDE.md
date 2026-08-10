# VibeCut — AI 影视解说/口播导演台 v1.2

## 最高准则：三位一体

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   🏗️ 系统 (System)        📚 知识 (Knowledge)           │
│   独特的、能跑的产品        最新、最深的技术积累            │
│                                                         │
│   "唯一用视频剪辑            "33篇知识库笔记              │
│    教AI全栈开发的             覆盖AI应用开发全链路          │
│    完整产品"                                               │
│                                                         │
│            └────────────┬────────────┘                   │
│                         │                               │
│                         ▼                               │
│              💰 商业 (Business)                          │
│              最贴合市场需求的变现路径                       │
│                                                         │
│              "AI全栈工程师实战培训课程"                    │
│              以 VibeCut 为教学案例                        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  原则:                                                   │
│  · 系统开发驱动知识积累 (每行代码都是教材)                  │
│  · 知识积累支撑商业价值 (每篇笔记都是课程资产)              │
│  · 商业反馈反哺系统迭代 (学员需求 → 产品方向)              │
│  · 三者不可偏废，任一维度的进展都拉动另外两个               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 产品定位：四台流水线

```
项目 ──→ 数据台 ──→ 编剧台 ──→ 分镜台 ──→ 剪映
制片      建索引     写解说词    分镜匹配     精剪导出
```

| 台 | 角色 | 职责 |
|---|---|---|
| 项目 | 制片 | 选项目，管进度 |
| 数据台 | DIT | 建索引，跑管线 |
| 编剧台 | 编剧 | 写解说词，生成脚本 |
| 分镜台 | 导演/分镜师 | 解说词 → 镜头匹配 |

## 项目类型

| 类型 | 项目 | 源素材 | 索引方式 |
|---|---|---|---|
| drama | 都挺好 | 46集 1080p | BGE (ASR + VLM) |
| interview | 杨老师教育 | 口播采访 | BGE (ASR, guest-only, speaker边界) |

## 目录

```
VibeCut/
├── vibecut-server/            ← Python 后端 (端口8765)
│   ├── main.py                     ← FastAPI 入口 (v1.1)
│   ├── build_index.py              ← BGE索引统一入口
│   ├── vlm_char_calibrate.py       ← VLM人物校准 (v1.2)
│   ├── analyze_episodes.py         ← VLM场景+ASR分析
│   ├── cross_calibrate.py          ← ASR↔VLM交叉校准
│   ├── clean_data.py               ← 数据清洗+场景合并
│   ├── script_agents.py            ← 编剧台 AI: v3+v4
│   ├── refine_segments.py          ← 口播精切引擎
│   ├── export_capcut.py            ← 剪映草稿导出
│
├── vibecut-web/               ← React 前端 (Vite, 端口3000)
│   └── src/
│       ├── pages/
│       │   ├── PlanningDesk.jsx  ← 编剧台: 脚本→精切→导出
│       │   ├── VibeEdit.jsx      ← 分镜台: 解说词→镜头匹配
│       │   ├── DataDesk.jsx      ← 数据台: 流水线管理
│       │   └── Home.jsx          ← 项目
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

- `/` — 项目 (Home)
- `/:project/:task/data` — 数据台 (DataDesk)
- `/:project/:task/planning` — 编剧台 (PlanningDesk)
- `/:project/:task/vibe` — 分镜台 (VibeEdit)

## 口播工作流 (v1.0)

```
编剧台:
  ASR → content report → 输入主题 → 🧠 AI生成脚本 (粗剪14段)
  → 审核粗段脚本 → ✂️ 精切 (refine) → sub_clips 22K+10C
  → 粗剪/精切 页签切换审核 → 导出 CapCut

分镜台:
  打开 → 口播自动建轨 (仅KEEP sub_clips → 时间轴)
  → 精切预览 (左面板 绿✅/红❌) → 微调

导出:
  segments.json (含sub_clips) → export_capcut.py → 剪映草稿
  CUT项音量=5% 便于识别删除
```

## 分镜策略 (导演思维)

解说词匹配镜头不再是"按句子搜关键词"，而是：

1. **分析解说叙事节拍** — 谁/在哪/做什么/什么情绪
2. **episode_marker 约束搜索范围** — 从 31,498 缩小到 500-800 候选
3. **BGE 语义搜索** — 找情感/氛围相似的场景
4. **frame_facts 人物过滤** — 校准后准确率 ~100%
5. **VLM depth_analysis** — 提供导演级的场景情绪解读

## 电视剧数据管线 (v1.3)

```
源视频 → analyze_episodes → clean_data → build_index
           (VLM场景+ASR)         (清洗+合并)    (BGE索引)
           
v1.3 VLM优化:
  · 角色参考照锚定 (character_portraits/)
  · 面部优先识别 → 反推场景 (严禁先判地点)
  · 剧集概要注入 (DeepSeek生成 ep_synopsis.json)
  · 上下文窗口传递人物 (串行分析)
  · 跳过序幕/落幕 (前1分+后3分)
  · 分组并发: 10场景/组, 组内串行, 多组并发
```

**v1.3 淘汰**:
- cross_calibrate.py (ASR↔VLM校准) — VLM源头已解决
- vlm_char_calibrate.py (T1-T4) — 不再需要后期校准
- T4 LLM校准 (DeepSeek) — 不再需要

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy)
- MPS: Apple Silicon GPU for BGE encoding (6.8GB VRAM limit)
- Moonshot API: MOONSHOT_API_KEY (编剧台LLM + 数据清洗 + 分镜推荐)
- MiMo API: MIMO_API_KEY (VLM画面分析, 仅电视剧)
- ffmpeg: 视频处理 + 代理生成
- Node: Vite + React 前端

## 关键数据文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `都挺好/semantic_embeddings.npy` | 92MB | BGE 嵌入 (31,498 × 768) |
| `都挺好/semantic_metas.json` | 7.5MB | 索引元数据 (VLM描述 + 字幕 + ASR) |
| `都挺好/sources_clean/epN/vlm_merged.json` | ~150KB/集 | VLM 场景分析 (含 frame_facts, _char_conflict) |
