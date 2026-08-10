# VibeCut 架构设计 v4

> 导演Agent化分镜：从机械匹配到叙事驱动的分镜设计。
> 2026-08-10 · 基于 FastAPI + React + DeepSeek导演推理。

---

## 一、全局工作流

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│  Phase 1     │  Phase 2     │  Phase 3     │  Phase 4     │
│  数据台·初步  │  编剧台       │  数据台·全面   │  分镜台       │
│  (素材准备)   │  (撰写脚本)   │  (深度索引)    │  (分镜匹配)   │
├──────────────┼──────────────┼──────────────┼──────────────┤
│              │              │              │              │
│ LLM: 批量处理 │ LLM: 交互辅助 │ LLM: 批量校对 │ 纯工程        │
│ 让人能看懂素材 │ 人主导+AI配合  │ 让机器能搜素材 │ 画面匹配+组装 │
│              │              │              │              │
└──────────────┴──────────────┴──────────────┴──────────────┘
        ↑ 全流程 AI 贯穿，区别在于调用方式（批量 vs 交互）↑
```

Phase A 和 Phase B 都在数据台，但目的不同、时机不同：

| | Phase A (写前) | Phase B (写后) |
|---|---|---|
| **目的** | 人看懂素材 | 机器搜索素材 |
| **输入** | 原始视频 | segments.json (脚本) |
| **产出** | 可浏览的文案/摘要 | 语义索引 + 质量报告 |
| **电视剧** | ASR + VLM初步分析 | 解说ASR校对 + BGE索引 + 数据清洗 |
| **口播** | ASR + LLM分类 + LLM分段 | ASR校对 + BGE索引 + 质量评分 |

---

## 二、后端架构 (v1.1 重构后)

### 2.1 模块分层

```
vibecut-server/
├── main.py                     ← FastAPI 入口 + 路由注册 (805行)
├── config.py                   ← CLI参数 + 项目配置 + 路径解析 (94行)
├── db.py                       ← SQLite 数据库层
│
├── handlers/                   ← 接口处理器 (2,107行)
│   ├── search.py               ← 6种搜索引擎 (语义/关键词/混合/ASR优先/深度/口播)
│   ├── tasks.py                ← 任务 CRUD (创建/状态/删除/列表)
│   ├── script_gen.py           ← AI脚本生成 (v3流水线/v4故事优先/精切 SSE)
│   ├── pipeline.py             ← 后台加工流水线 (电视剧+口播)
│   ├── media.py                ← 媒体服务 (代理视频/片段提取/预览/导出)
│   ├── dialogue.py             ← 对话+台词 (chat/dialogue_match/storyboard/analyze)
│   └── static.py               ← SPA前端回退 + 任务目录文件服务
│
├── lib/                        ← 共享基础设施 (377行)
│   ├── llm.py                  ← 统一LLM调用 (Moonshot/MiMo, 消除10种重复)
│   ├── embeddings.py           ← BGE模型单例管理
│   ├── sse.py                  ← 可复用SSE发射器 + 心跳
│   ├── env.py                  ← 统一.env加载
│   └── subprocess_runner.py    ← 统一子进程执行器
│
├── script_agents.py            ← 编剧台 AI Agent (v3搜索+v4故事优先)
├── refine_segments.py          ← 口播精切引擎
└── (独立脚本...)
    ├── build_index.py          ← BGE索引统一入口
    ├── analyze_episodes.py     ← 电视剧: 场景+ASR+VLM
    ├── classify_transcript.py  ← 口播: LLM分类
    ├── clean_interview_data.py ← 口播: 清洗+说话人
    └── export_capcut.py        ← 剪映草稿导出
```

### 2.2 框架选型

| 维度 | v1.0 (`http.server`) | v1.1 (FastAPI) |
|---|---|---|
| 路由 | 手动 if/elif 链 (200行) | `@app.get/post` 装饰器 |
| 文件上传 | 手写 150行 boundary 解析 | `UploadFile` 自动 |
| CORS | 每个端点手动加头 | `CORSMiddleware` 一行 |
| SSE | 手写 `wfile.write` (3次重复) | `StreamingResponse` |
| API 文档 | ❌ | ✅ Swagger (`/docs`) |
| 输入校验 | ❌ 裸 `json.loads` | Pydantic (可逐步加) |

---

## 三、数据台：双阶段流水线

### 3.1 Phase A — 素材准备 (v3 结构化视觉元数据)

```
电视剧流水线 v3:                    口播流水线:
  analyze_episodes.py               classify_transcript.py
  ├─ Layer 1: DeepSeek 读ASR        ├─ LLM分类 (content/meta/guide/filler)
  │   → scene_map.json              ├─ LLM分段 (5-8个主题组)
  │    (人物/地点/事件/情绪, 场景级)   └─ 生成标准化文案
  ├─ Layer 2: ASR 精确时间锚定
  └─ Layer 3: MiMo VLM 结构化输出     clean_interview_data.py
      → vlm_seg_cache_v3.json        ├─ LLM文本清洗 (去废词/口误)
        (景别/构图/视角/情绪/强度       ├─ 说话人识别 (host/guest)
         /光线/动作, 每段8个字段)       └─ 输出 classified_enhanced.json

v3 关键变化:
  · VLM 不再认人脸，只负责视觉元数据
  · 场景段级索引 (不再做10s切片展开)
  · 814 场景段 / 46集，572种情绪标签
  · 景别分布: 中景58%, 近景36%, 全景4%
  · 构图分布: 单人51%, 双人38%, 三人6%

产出:                              产出:
  sources/ep{N}/                      sources_clean/
  ├─ scene_map.json                   ├─ classified.json
  ├─ vlm_seg_cache_v3.json           ├─ classified_enhanced.json
  ├─ asr_result.json                  └─ segmented.json
  └─ scenes.json
```

### 3.2 Phase B — 深度索引

```
电视剧流水线:                       口播流水线:
  build_index.py (自动识别项目类型)
  ├─ v3场景段 → BGE索引              ├─ 优先使用 enhanced 数据
  │  (结构化标签注入索引文本)          ├─ speaker边界断开分块
  │  "[景别:中景] [构图:双人]..."     ├─ guest-only 建索引
  └─ npy + json mmap                 └─ BGE 768维 → .npy + .json
```

---

## 四、编剧台：通用脚本工厂

### 4.1 两条流水线

#### v3 搜索流水线 (run_pipeline) — 电视剧/有索引的场景

```
策划师(LLM) → 文案师(BGE搜索) → 精编师(LLM压缩) → 审核师(LLM审核+修复)
                    ↕
              BGE 语义索引
```

**API**: `POST /script/generate_script_stream` (SSE 流式)

#### v4 故事优先流水线 (story_first_pipeline) — 口播采访

```
LLM 通读全部 ASR → 理解完整故事 → 一次性输出分组段落脚本
```

**API**: `POST /script/generate_story_first` (SSE 流式, ~12s 完成)

**对比**:

| | v3 搜索流水线 | v4 故事优先 |
|---|---|---|
| 策略 | 逐段搜索 → 拼句子 | 通读全文 → 设计故事 |
| 调用次数 | 4-8 次 LLM + 8 次 BGE | 1 次 LLM |
| 耗时 | ~40s | ~12s |
| 段落结构 | 扁平句子列表 | 分组段落（section → clips） |
| 适用 | 电视剧（多集、多镜头） | 口播采访（单文件、单镜头） |

---

## 五、分镜台 v4：导演Agent化

### 5.1 范式转变

```
v3 (机械匹配):                       v4 (导演Agent):
  解说句1 → 搜索"苏大强" → 贴镜头         解说段 → 导演理解叙事 → 设计分镜方案
  解说句2 → 搜索"对峙"   → 贴镜头                   ↓
  解说句3 → 搜索"明玉"   → 贴镜头           逐镜结构化查询 → 数据匹配
                                                    ↓
  结果: 碎片化拼贴, 缺乏视觉叙事              结果: 有递进关系的分镜序列
```

**核心理念**: 从"解说词作为搜索字符串"升级为"解说词作为叙事意图 → 翻译为导演语汇 → 精确查询源素材"。

### 5.2 导演Agent 三层架构

```
POST /storyboard_suggest { narration, segment_context, cover }
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ Layer 1: LLM 叙事理解 (DeepSeek)                      │
│   输入: 解说词 + cover上下文 + 角色出场统计             │
│   推理: 主题 → 主角推断 → 情绪弧线 → 分镜设计           │
│   输出: { main_char, shots: [{purpose, characters,    │
│           shot_size, emotional_tone, intensity_min}]} │
├─────────────────────────────────────────────────────┤
│ Layer 2: 人物交叉校验                                  │
│   · cover 中出现的角色 = 决定性证据, 覆盖LLM推断         │
│   · 角色必须在 scene_map 已知范围内                     │
│   · 场景数 < 10 的角色标记为可疑                        │
├─────────────────────────────────────────────────────┤
│ Layer 3: 结构化匹配引擎 (_match_shot_query)              │
│   在 46集×814场景段 中逐镜过滤:                         │
│     · 人物精确匹配 (+15/人)                             │
│     · 情绪标签匹配 (+8/命中)                            │
│     · 强度阈值过滤 (+3/级)                              │
│     · 景别精确匹配 (+6) / 近似匹配 (按距离衰减)          │
│     · 地点/动作提示匹配 (+4)                            │
│   每镜返回 top-5 候选 + 备选方案                        │
└─────────────────────────────────────────────────────┘
         │
         ▼
{ shots: [{purpose, candidates: [{ep,start,end,
   visual_summary,shot_size,emotional_tone,...}]}] }
```

### 5.3 降级机制

导演Agent 失败时自动降级为 v3 分层关键词匹配（scene_map人物过滤 + KW_MAP情绪关键词 + BGE轻量精排 + ASR锚定）。

### 5.4 前端交互

```
┌────────────┬──────────────────┬──────────────────────┐
│ ScriptPanel│ Preview+Timeline │ StoryboardSequence   │
│ (段落级)    │                  │                       │
│            │                  │ 镜1: 建立苏明成状态    │
│ 🎣 Hook    │                  │  EP15 [600s] 中景 低落│
│ S0 台词    │                  │  [预览] [替换] [加入]   │
│   解说 ▶   │                  │                       │
│            │                  │ 镜2: 展现窝里横       │
│ S1 台词    │                  │  EP26 [150s] 中景 愤怒│
│   解说 ▶   │                  │  [预览] [替换] [加入]   │
│            │                  │                       │
│            │                  │ [全部加入时间线]       │
│            │                  ├──────────────────────│
│            │                  │ SourceInspector      │
├────────────┴──────────────────┴──────────────────────┤
│ Timeline (Elah 4轨)                                   │
└──────────────────────────────────────────────────────┘
```

- **ScriptPanel**: 段落级，台词行 + 解说行分离。点击解说行 = 展开 + 触发策划分镜
- **StoryboardSequence**: 展示导演Agent输出的分镜序列，每镜带5个备选候选
- **"替换"按钮**: 循环切换到下一个备选候选
- **"加入时间线"**: 单镜或全部一键导入 Elah 时间轴

---

## 六、目录结构

```
VibeCut/
├── vibecut-server/
│   ├── main.py                     ← FastAPI 入口
│   ├── config.py
│   ├── db.py
│   ├── lib/                        ← 共享基础设施
│   ├── handlers/                   ← 接口处理器
│   ├── script_agents.py            ← AI Agent
│   ├── refine_segments.py          ← 精切引擎
│   ├── build_index.py              ← BGE索引
│   └── (数据处理脚本...)
│
├── vibecut-web/
│   └── src/
│       └── pages/
│           ├── DataDesk.jsx
│           ├── PlanningDesk.jsx
│           └── VibeEdit.jsx
│
├── projects/
│   ├── 都挺好.json
│   └── 杨老师教育.json
│
├── 都挺好/                         ← 电视剧项目
│   ├── sources/ep{N}/
│   ├── sources_clean/ep{N}/
│   ├── proxies/
│   ├── semantic_embeddings.npy
│   └── tasks/
│
└── 杨老师教育/                     ← 口播项目
    ├── sources/
    ├── sources_clean/
    │   ├── classified.json
    │   ├── classified_enhanced.json
    │   ├── semantic_embeddings.npy
    │   └── semantic_metas.json
    ├── proxies/
    └── tasks/
```

---

> 最后更新：2026-08-10 · v4.0.0 · 导演Agent化
