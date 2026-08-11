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
| 编剧台 | 编剧 | 写解说词，生成脚本 (interview + drama双模式) |
| 分镜台 | 导演/分镜师 | 解说词 → 镜头匹配 |

## 项目类型

| 类型 | 项目 | 源素材 | 编剧模式 |
|---|---|---|---|
| drama | 都挺好 | 46集 1080p | AI编剧Agent (故事师+策划师+文案师, scene_map驱动) |
| interview | 杨老师教育 | 口播采访 | AI选句编排 (v3/v4 pipeline) |

## 目录

```
VibeCut/
├── vibecut-server/            ← Python 后端 (端口8765)
│   ├── main.py                     ← FastAPI 入口 (v1.2)
│   ├── build_index.py              ← BGE索引统一入口
│   ├── analyze_episodes.py         ← VLM v2.4: 三层推理 (DeepSeek→ASR→VLM)
│   ├── script_agents.py            ← interview编剧台 AI: v3+v4
│   ├── drama_script_agents.py      ← drama编剧台 AI: 故事师+策划师+文案师 (新)
│   ├── refine_segments.py          ← 口播精切引擎
│   ├── export_capcut.py            ← 剪映草稿导出
│   │
│   ├── handlers/
│   │   ├── search.py               ← 搜索 (BGE语义/ASR关键词/ASR锚定)
│   │   ├── dialogue.py             ← 对话匹配 + AI聊天 (184行)
│   │   ├── storyboard.py           ← 导演Agent v8.5: PRIMARY+SECONDARY (581行)
│   │   ├── script_gen.py           ← interview AI脚本生成 (SSE)
│   │   ├── script_drama.py         ← drama AI脚本生成 SSE handler (新)
│   │   ├── pipeline.py             ← 后台流水线
│   │   ├── media.py                ← 媒体服务
│   │   ├── static.py               ← SPA前端回退
│   │   └── prompts/
│   │       ├── director.py         ← DIRECTOR_PROMPT 模板 (150行)
│   │       └── script_drama.py     ← 编剧Agent Prompt模板 (新)
│   │
│   └── lib/
│       ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo/DeepSeek)
│       ├── embeddings.py           ← BGE模型单例管理
│       ├── sse.py                  ← SSE发射器 + 心跳
│       ├── vlm_cache.py            ← VLM 场景缓存加载 (111行)
│       ├── storyboard_match.py     ← 分镜匹配引擎 (195行)
│       └── scene_map.py            ← 场记Agent: scene_map + synopsis生成
│
├── vibecut-web/               ← React 前端 (Vite, 端口3000)
│   └── src/
│       ├── pages/
│       │   ├── PlanningDesk.jsx  ← 编剧台: interview+drama双模式
│       │   ├── VibeEdit.jsx      ← 分镜台: 解说词→镜头匹配
│       │   ├── DataDesk.jsx      ← 数据台: 流水线管理+质量评分
│       │   └── Home.jsx          ← 项目
│       ├── components/
│       │   ├── ScriptPanel.jsx   ← 脚本面板 (精切/粗段自适应)
│       │   ├── ChatPanel.jsx     ← AI搜索面板 (调 storyboard_suggest)
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
└── vibecut.db                 ← SQLite (不提交git)
```

## 启动

```bash
# 后端
cd vibecut-server
/opt/anaconda3/bin/python3 main.py --project 都挺好 --task Task0804 --port 8765

# 前端
cd vibecut-web && npm run dev
```

## 后端 API

| 端点 | 方法 | 说明 |
|---|---|---|
| GET /search?q=&mode=semantic | GET | BGE语义搜索 |
| GET /segments.json?task= | GET | 任务分段 (DB→文件fallback) |
| POST /storyboard_suggest | POST | 分镜推荐 v8.5 (导演Agent: beats+PRIMARY+SECONDARY) |
| POST /dialogue_match | POST | 台词→ASR锚定 (第一句滑窗, 无需LLM) |
| POST /script/generate_script_stream | POST | v3搜索流水线 SSE (interview) |
| POST /script/generate_story_first | POST | v4故事优先 SSE (interview) |
| POST /script/generate_drama_script | POST | **v1 编剧Agent SSE (drama) — 新** |
| POST /script/refine | POST | 精切 SSE |
| POST /tasks/create_json | POST | 创建任务 (支持无docx, AI编剧模式) |
| GET /data/quality?project= | GET | 每集数据质量统计 (ASR+VLM+scene_map+概要) |
| GET /proxies/manifest | GET | 代理视频清单 |
| GET /status | GET | 健康检查 |

## 前端路由

- `/` — 项目 (Home)
- `/:project/:task/data` — 数据台 (DataDesk)
- `/:project/:task/planning` — 编剧台 (PlanningDesk, interview+drama双模式)
- `/:project/:task/vibe` — 分镜台 (VibeEdit)

## 电视剧数据管线 (v3.1)

### VLM 分析 — 三层推理 + 情绪锚定

```
ASR 转写 → DeepSeek 场记Agent 生成 scene_map (人物+地点+事件+情绪)
         → VLM 画面分析 (scene_map mood 锚定, 1/3+2/3 位置采帧)
```

| 指标 | v1.3 (旧) | v3.1 (当前) | 变化 |
|---|---|---|---|
| VLM 调用/集 | 241 次 | 10-25 次 | ↓90% |
| Token/集 | 692K | 43K | ↓94% |
| 关键帧采样 | 首尾帧 | 1/3+2/3 位置 | 避免切点边界, 捕获冲突画面 |
| 情绪准确度 | VLM 独立判断 | scene_map mood 锚定 | 零情绪矛盾 |
| 人物识别 | VLM 认人脸 (~29% 错误) | scene_map 确定 (0% 错误) | ✅ |

三层:
1. **DeepSeek 场记Agent** (`lib/scene_map.py`) → scene_map (人物+地点+事件+情绪+时间)
2. **ASR 关键词锚定** → 精准时间边界
3. **VLM 画面理解** — mood 锚定 + 结构化JSON输出

### scene_map 数据质量

- 46集共1511个场景，event/mood完整率 100%
- 场景维度: time_range, location, characters, event, mood
- 每个场景对话段60-120s，相邻场景间隔≤15s

## 编剧Agent v1 — Drama脚本生成 (新)

**核心理念**: 三个独立Agent角色协作，将46集剧情结构化数据转化为影视解说脚本。人提供创意方向（选题+选集+时长），Agent负责执行。

```
选题+选集+时长 → 故事师(全剧概要→故事地图) → 策划师(故事地图→章节方案)
                                                        │
                                                        ▼
                                              文案师(章节+scene_map→解说词+scene_query)
                                                        │
                                                        ▼
                                              程序校验(scene_query↔scene_map 一致性)
                                                        │
                                                        ▼
                                              segments.json (带episode_marker+source_start/end)
```

**核心Agent**:
- **故事师** (`story_master_agent`) — 通读46集剧情概要 → 提取人物弧光/转折点/高光场景/选题建议
- **策划师** (`narrative_planner_agent`) — 故事地图+选题→4-7章叙事方案(每章含场景锚点+导演手法+时长估算)
- **文案师** (`script_writer_agent`) — 章节方案+scene_map→解说词+scene_query(含原剧台词highlight_text)

**7层写作结构**:
1. 核心视角 — 每章聚焦单一人物/主题
2. 开场钩子 — ≤50字观点句，3秒抓住注意力
3. 原剧台词 — highlight_text作为"原声证据"
4. 解说节奏 — 钩子→背景→事件→高潮→升华
5. 语言风格 — 网感+幽默+金句，禁止干巴复述
6. 人物心理 — 分析动机，不只讲"发生了什么"
7. 结尾金句 — 价值观升华，制造共鸣和转发欲

**审核策略**: 程序校验替代LLM审核（scene_query与scene_map精确匹配，修正time_range偏移，0 LLM调用节省约70s）

**关键模块**:
- `drama_script_agents.py` — 三个Agent + 编排器 `run_drama_pipeline()`
- `handlers/script_drama.py` — SSE端点处理函数
- `handlers/prompts/script_drama.py` — Prompt模板 (故事师/策划师/文案师)
- `lib/scene_map.py` — 场记Agent (scene_map已优化至100% event/mood覆盖)

**API**: `POST /script/generate_drama_script`
```json
{"topic": "苏明成人物线：从妈宝到守护者", "episodes": [1,3,21,39,41,45], "target_duration": 240}
```

**产出**: segments.json (兼容VibeEdit/ScriptPanel/Storyboard)
```json
{"narration_text": "...", "highlight_text": "...", "scene_query": {"episode":21, "time_range":[240,330], "characters":["苏明成","苏明玉"], "mood":"愤怒"}, "episode_marker":{"episode":21, "approx_minute":4.0}, "source_start":240.0, "source_end":330.0, "mode":"A"}
```

## 分镜匹配策略 (v8.5 — 导演Agent)

**核心理念**: LLM 是导演，将解说词拆解为叙事节拍（beats），运用六种导演手法，为每个节拍生成结构化 shot query，通过匹配引擎在 VLM 场景缓存中找到最优画面。

```
解说词 → DeepSeek 导演叙事分析 → beats (节拍) + shots (PRIMARY+SECONDARY)
         │
         ▼
   lib/storyboard_match.py — 多维度评分引擎
   剧集锚定 + 人物匹配 + 场景情绪冲突补偿 + 景别 + 地点模糊匹配 + 动作滑窗匹配
         │
         ▼
   最优候选镜头 (PRIMARY score ≥ 40+)
```

**关键模块**:
- `handlers/storyboard.py` — 导演Agent 入口 + _fallback_storyboard_suggest
- `lib/storyboard_match.py` — 纯函数匹配引擎 (独立可测试)
- `lib/vlm_cache.py` — 46集 VLM 场景缓存懒加载
- `lib/scene_map.py` — 场记Agent: scene_map + synopsis 生成
- `handlers/prompts/director.py` — DIRECTOR_PROMPT 模板

**优势**:
- 叙事驱动分镜 (非机械句子匹配)
- PRIMARY+SECONDARY 主辅镜头层次
- scene_map mood 情绪冲突补偿 (VLM 采样偏差容错)
- 论证式解说词识别 (argument beat 自动拆解)
- 第一句锚定 ASR 台词定位 (dialogue_match, 0ms 延迟)

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy)
- MPS: Apple Silicon GPU for BGE encoding (6.8GB VRAM limit)
- DeepSeek API: DEEPSEEK_API_KEY (编剧Agent + scene_map + 分镜推荐)
- Moonshot API: MOONSHOT_API_KEY (interview编剧台LLM)
- MiMo API: MIMO_API_KEY (VLM画面分析)
- ffmpeg: 视频处理 + 代理生成
- Node: Vite + React 前端

## 关键数据文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `都挺好/semantic_embeddings.npy` | 87MB | BGE 嵌入 (29,797 × 768) |
| `都挺好/semantic_metas.json` | 7MB | 索引元数据 (VLM描述 + ASR) |
| `都挺好/sources/epN/scene_map.json` | ~3KB/集 | 场记Agent: 场景-人物-事件-情绪-时间映射 (46集1511场景, 100%完整) |
| `都挺好/sources/epN/vlm_seg_cache_v3.json` | ~10KB/集 | VLM 画面分析 (25段/集, mood锚定) |
| `都挺好/sources/epN/ep_synopsis.json` | ~500B/集 | DeepSeek 剧情概要 |
| `都挺好/sources/epN/asr_result.json` | ~70KB/集 | faster-whisper ASR 转写 |
| `都挺好/tasks/文案脚本.json` | ~5KB | AI编剧生成的脚本 (兼容VibeEdit/ScriptPanel) |
