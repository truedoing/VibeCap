# VibeCut — AI 影视解说/口播导演台 v2.5

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
│   ├── analyze_episodes.py         ← VLM v2.4: 三层推理 (DeepSeek→ASR→VLM)
│   ├── script_agents.py            ← 编剧台 AI: v3+v4
│   ├── refine_segments.py          ← 口播精切引擎
│   ├── export_capcut.py            ← 剪映草稿导出
│   │
│   ├── handlers/
│   │   ├── search.py               ← 搜索 (BGE语义/关键词/分层匹配)
│   │   ├── dialogue.py             ← 分镜推荐 v3: scene_map结构化匹配
│   │   ├── script_gen.py           ← AI脚本生成 (SSE)
│   │   ├── pipeline.py             ← 后台流水线
│   │   ├── media.py                ← 媒体服务
│   │   └── static.py               ← SPA前端回退
│   │
│   └── lib/
│       ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo/DeepSeek)
│       ├── embeddings.py           ← BGE模型单例管理
│       └── sse.py                  ← SSE发射器 + 心跳
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
| POST /storyboard_suggest | POST | 分镜推荐 v3 (scene_map结构化匹配) |
| POST /script/generate_script_stream | POST | v3搜索流水线 SSE |
| POST /script/generate_story_first | POST | v4故事优先 SSE (口播专用) |
| POST /script/refine | POST | 精切 SSE |
| GET /data/quality?project= | GET | 每集 VLM/ASR 统计 |
| GET /proxies/manifest | GET | 代理视频清单 |
| GET /status | GET | 健康检查 |

## 前端路由

- `/` — 项目 (Home)
- `/:project/:task/data` — 数据台 (DataDesk)
- `/:project/:task/planning` — 编剧台 (PlanningDesk)
- `/:project/:task/vibe` — 分镜台 (VibeEdit)

## 电视剧数据管线 (v2.4)

### VLM 分析 — 三层推理架构

```
ASR 转写 → DeepSeek 生成 scene_map (人物+地点+事件) → VLM 只描述画面 (已知人物)
```

| 指标 | v1.3 (旧) | v2.4 (新) | 变化 |
|---|---|---|---|
| VLM 调用/集 | 241 次 | 10-25 次 | ↓90% |
| Token/集 | 692K | 43K | ↓94% |
| 人物识别 | VLM 认人脸 (~29% 错误) | scene_map 确定 (0% 错误) | ✅ |
| 角色照锚定 | 每10场景发送 | 废除 | ✅ |
| 描述格式 | 7种混乱 | 统一 ≤80字 | ✅ |

三层:
1. **DeepSeek 读 ASR + synopsis** → 结构化场景-人物-时间映射 (scene_map)
2. **ASR 关键词锚定** → 精准时间边界
3. **VLM 只做画面理解** — 已知人物/地点/剧情，不认人

### 淘汰的管线步骤
- `cross_calibrate.py` — ASR↔VLM 交叉校准 (scene_map 已替代)
- `vlm_char_calibrate.py` — VLM 人物校准 T1-T4 (VLM 不再认人)
- `clean_data.py` 的 VLM 字幕部分 — VLM 不再输出硬字幕
- BGE 全量语义搜索 — 分镜匹配改为 scene_map 结构化搜索

## 分镜匹配策略 (v3 — 分层结构化匹配)

**核心理念**: 解说词匹配镜头 = 在 scene_map 中查询结构化字段，不再依赖 BGE 全量语义搜索。

```
解说词 → 提取人物/情绪关键词 → scene_map 过滤 (人物+事件+地点)
→ VLM描述语义评分 (7类情绪关键词库) → BGE轻量精排 (仅top-20)
→ ASR 精确时间锚定 (精确到秒)
```

**优势**:
- 从 31K 候选 → ~100 段 (人物过滤)
- 天然场景段去重 (保证多样性)
- 响应 0.1s (vs BGE 8s)
- 不需要 10s 切片展开

**BGE 仍保留用于**: 编剧台解说词生成/策划等语义推理场景 (非实时匹配)

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy)
- MPS: Apple Silicon GPU for BGE encoding (6.8GB VRAM limit)
- Moonshot API: MOONSHOT_API_KEY (编剧台LLM + 分镜推荐)
- MiMo API: MIMO_API_KEY (VLM画面分析)
- DeepSeek API: DEEPSEEK_API_KEY (scene_map 生成 + synopsis)
- ffmpeg: 视频处理 + 代理生成
- Node: Vite + React 前端

## 关键数据文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `都挺好/semantic_embeddings.npy` | 87MB | BGE 嵌入 (29,797 × 768) |
| `都挺好/semantic_metas.json` | 7MB | 索引元数据 (VLM描述 + ASR) |
| `都挺好/sources/epN/scene_map.json` | ~3KB/集 | DeepSeek 场景-人物-时间映射 |
| `都挺好/sources/epN/vlm_seg_cache_v2.json` | ~4KB/集 | VLM 场景段描述 (10-25段/集) |
| `都挺好/sources/epN/vlm_analysis_sliced.json` | ~70KB/集 | VLM 描述按10s展开 (BGE索引用) |
