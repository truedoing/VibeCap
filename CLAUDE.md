# VibeCut — AI 影视解说/口播导演台 v1.4

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

## 产品定位：五台流水线

```
项目 ──→ 数据台 ──→ 脚本台 ──→ 分镜台 ──→ 剪映
制片      建索引     定稿+配音    分镜匹配    精剪导出
```

| 台 | 角色 | 职责 |
|---|---|---|
| 项目 | 制片 | 选项目，管进度 |
| 数据台 | DIT | 建索引，跑管线 |
| 脚本台 | 编剧 | 看方案全文 + 编辑脚本 + 配音 (选段生成/试听/克隆音色) |
| 分镜台 | 导演/分镜师 | 解说词 → 镜头匹配 |

## 项目类型

| 类型 | 项目 | 源素材 | 脚本来源 |
|---|---|---|---|
| drama | 都挺好 | 46集 1080p | 外部导入 JSON（扣子/WorkBuddy）+ AI V2 单 LLM |
| interview | 杨老师教育 | 口播采访 | 外部导入 + 素材选句编排 |

## 目录

```
VibeCut/
├── vibecut-server/            ← Python 后端 (端口8765)
│   ├── main.py                     ← FastAPI 入口 (v1.4)
│   ├── build_index.py              ← BGE索引统一入口 (在 cli/)
│   ├── analyze_episodes.py         ← VLM v2.4: 三层推理 (在 cli/)
│   │
│   ├── handlers/
│   │   ├── search.py               ← 搜索 (BGE语义/ASR关键词)
│   │   ├── storyboard.py           ← 导演Agent v8.5: PRIMARY+SECONDARY
│   │   ├── script_drama.py         ← drama 脚本生成 v2 (单 LLM)
│   │   ├── voiceover.py            ← 配音: 规则驱动方案 + MiMo TTS
│   │   ├── pipeline.py             ← 后台流水线
│   │   ├── media.py                ← 媒体服务
│   │   ├── static.py               ← SPA前端回退
│   │   └── prompts/
│   │       ├── director.py         ← DIRECTOR_PROMPT 模板
│   │       └── script_drama.py     ← SCRIPT_V2_PROMPT 模板
│   │
│   └── lib/
│       ├── llm.py                  ← 统一LLM调用 (Moonshot/DeepSeek)
│       ├── embeddings.py           ← BGE模型单例管理
│       ├── sse.py                  ← SSE发射器 + make_emitter
│       ├── vlm_cache.py            ← VLM 场景缓存加载 (111行)
│       ├── storyboard_match.py     ← 分镜匹配引擎 (195行)
│       └── scene_map.py            ← 场记Agent: scene_map + synopsis生成
│
├── vibecut-web/               ← React 前端 (Vite, 端口3000)
│   └── src/
│       ├── pages/
│       │   ├── ScriptDesk.jsx   ← 脚本台: 方案全文 + 编辑 + 配音
│       │   ├── VibeEdit.jsx      ← 分镜台: 解说词→镜头匹配
│       │   ├── DataDesk.jsx      ← 数据台: 流水线管理+质量评分
│       │   └── Home.jsx          ← 项目
│       ├── components/
│       │   ├── PlanPanel.jsx    ← 方案全文面板 (论点/装置/情绪曲线/图表)
│       │   ├── VoicePanel.jsx   ← 配音面板 (选段生成/试听/克隆音色)
│       │   ├── ScriptPanel.jsx  ← 脚本面板 (精切/粗段自适应)
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
| POST /script/import_external_json | POST | 外部解说 JSON 导入（扣子/WorkBuddy） |
| POST /script/generate_drama_script_v2 | POST | drama 脚本生成 v2 (单 LLM) SSE |
| POST /voiceover/voices | GET | 音色列表（预设 + 克隆） |
| POST /voiceover/create_voice | POST | 新建克隆音色（上传参考音频） |
| POST /voiceover/generate_stream | POST | 一键全量配音 SSE (规则方案 + MiMo TTS) |
| POST /voiceover/regenerate_segment | POST | 单段配音 SSE |
| GET /data/quality?project= | GET | 每集数据质量统计 (ASR+VLM+scene_map+概要) |
| GET /proxies/manifest | GET | 代理视频清单 |
| GET /status | GET | 健康检查 |

## 前端路由

- `/` — 项目 (Home)
- `/:project/:task/data` — 数据台 (DataDesk)
- `/:project/:task/script` — 脚本台 (ScriptDesk, 方案全文 + 编辑 + 配音)
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

### VLM 管线关键修复 (v8.5.6)

1. **MiMo v2.5 推理模型适配**: MiMo 是推理模型，`reasoning_content` 占满 token 导致 `content` 为空 → NoneType 错误。修复：content 空时 fallback 到 reasoning_content，max_tokens 1200→4000。
2. **抽帧缺失**: `pick_keyframes_for_segment` 的 `n==0` 分支漏 `return` 返回 None。修复：补 return。
3. **帧目录误删**: `analyze_episode` 传 `--proxy` 时 `rmtree(frames)` 强制重抽帧，并发 ffmpeg 超时。修复：复用已有帧。
4. **ASR 人名标准化**: whisper 同音字误识别人名（朱莉→朱丽、明诚→明成、宋明成→苏明成等）。修复：`cli/normalize_asr_names.py` 全量修复 46 集 326 处 + scene_map prompt 加"人名归一化铁律"。

**结果**: 46 集 VLM 全部完成，空响应 452→17，情绪矛盾 22→0。

## 脚本台 — Drama脚本定稿

### V2（当前）：单 LLM + 方法论

**范式**: 放弃多 Agent 协作，改为「单 LLM + 方法论」一次产出。多 Agent 经过十余轮优化已达瓶颈（环节多、割裂、难调），单 LLM 直出质量反而更好（公网 LLM 对老流行剧的知识比自建 ASR 更可靠）。

```
选题 → DeepSeek(SCRIPT_V2_PROMPT) → 完整脚本(论点+装置+起承转合+名场面function) → 落盘 segments.json
```

**SCRIPT_V2_PROMPT 方法论**（浓缩的创作规范）:
1. 反常识论点（认知增量）+ 叙事装置（点睛不轰炸）
2. 起承转合的故事结构（不是论证结构）
3. 名场面穿插（type: narration/dialogue + function: 锚定/举证/引爆/爆点）
4. 金句不复读（≤2次）、升华回论点不鸡汤
5. 剥层（表层→剥层→升华，复述为骨议论为肉）

**关键模块**:
- `handlers/prompts/script_drama.py` → `SCRIPT_V2_PROMPT`（单 LLM 方法论）
- `handlers/script_drama.py` → `generate_drama_script_v2()`（单 LLM 生成函数）
- `routers/sse_script.py` → `POST /script/generate_drama_script_v2`

**API**: `POST /script/generate_drama_script_v2`
```json
{"topic": "苏大强与保姆小蔡：保姆三句话，骗走一套房", "target_duration": 300}
```

### 产出: segments.json (兼容 VibeEdit/ScriptPanel/Storyboard)
```json
{"narration_text": "...", "highlight_text": "...", "episode_marker":{"episode":21}, "mode":"A"}
```

## 配音 — 脚本台内嵌（选段生成 + 试听 + 克隆音色）

**定位**: 配音已从独立「配音台」并入脚本台右侧面板。逐段用 MiMo API 生成，支持预设音色 + 全局克隆音色。

```
选中段(narration_text) → 规则驱动方案(narrative + 1.0x) → MiMo TTS
                       → 落盘 narr_{seg_id:03d}.wav + narration.json + tts_meta.json
                       → 反写 segments.json (audio_duration + audio_path)
```

**关键模块**:
- `handlers/voiceover.py` — `generate_voiceover()`(全量) + `regenerate_segment()`(单段)
- `lib/voice_store.py` — 全局音色库（预设 + 克隆），持久化到 voices/
- `tts_engine.py` — MiMo API 单引擎 (预设音色 + voiceclone)

**API**:
- `GET /voiceover/voices` — 音色列表
- `POST /voiceover/create_voice` — 新建克隆音色（上传参考音频）
- `POST /voiceover/generate_stream` — 一键全量配音 SSE
- `POST /voiceover/regenerate_segment` — 单段配音 SSE

**产出**: work_dir/tts_segments/narr_*.wav + segments.json 带 audio_duration (分镜台消费)

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

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy)
- MPS: Apple Silicon GPU for BGE encoding (6.8GB VRAM limit)
- DeepSeek API: DEEPSEEK_API_KEY (脚本生成 + scene_map + 分镜推荐)
- MiMo API: MIMO_API_KEY / MIMO_TTS_API_KEY (VLM画面分析 + TTS配音)
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
