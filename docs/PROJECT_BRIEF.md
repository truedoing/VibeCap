# VibeCut — AI 影视解说 / 口播导演台（项目综合介绍 v1.4）

> 用途：给外部 AI（如 ChatGPT 网页）快速建立项目上下文。内容截至 2026-08。

## 一、这是什么

VibeCut 是一个 **AI 影视解说 & 口播视频导演台**——从"一部 46 集的电视剧"或"一段口播采访"出发，自动产出**解说脚本 + 配音 + 分镜匹配 + 剪辑成片**的一站式工具。整个项目用 AI 辅助开发，前端 React + 后端 Python，是一个**能跑的真实产品**，同时也是作者教学项目的主角。

它的核心主张是"**三位一体**"：

| 维度 | 内容 | 原则 |
|---|---|---|
| 🏗️ System（系统） | 独特的、能跑的产品 | 系统开发驱动知识积累（每行代码都是教材） |
| 📚 Knowledge（知识） | 最新、最深的技术积累（40+ 篇知识库笔记） | 知识积累支撑商业价值（每篇笔记都是课程资产） |
| 💰 Business（商业） | 最贴合市场需求的变现路径 | 商业反馈反哺系统迭代（学员需求→产品方向） |

商业目标：**AI 全栈工程师实战培训课程**，以 VibeCut 为教学案例。

## 二、产品形态：五台流水线

```
项目 ──→ 数据台 ──→ 脚本台 ──→ 分镜台 ──→ 剪映
制片      建索引     定稿+配音    分镜匹配    精剪导出
```

| 台 | 角色 | 职责 |
|---|---|---|
| 项目 | 制片 | 选项目，管进度 |
| 数据台 | DIT | 建索引，跑数据管线 |
| 脚本台 | 编剧 | 看方案全文 + 编辑脚本 + 配音（选段生成/试听/克隆音色） |
| 分镜台 | 导演 | 解说词 → 镜头匹配（PR 风格源检视器 + 时间轴） |
| 剪映 | 精剪 | 导出成片素材 |

**两种项目类型**：
- **drama（电视剧）**：都挺好（46 集 1080p），外部导入 JSON（扣子/WorkBuddy）+ AI 脚本
- **interview（口播）**：杨老师教育，口播采访 + 素材选句编排

## 三、技术架构

### 后端（Python, 端口 8765）

v1.4 架构 = **瘦入口 + 按功能域拆分**：

```
vibecut-server/
├── main.py          ← FastAPI 入口（瘦入口，注册 13 个 router）
├── routers/         ← API 路由（search / segments / ai / sse_script / sse_voiceover / pipeline / export / media / picks ...）
├── handlers/        ← 业务逻辑（search / storyboard / script_drama / voiceover / pipeline / media ...）
├── lib/             ← 公共库（llm / embeddings / sse / scene_map / storyboard_match / vlm_cache / segments_store ...）
├── cli/             ← 数据管线脚本（build_index / analyze_episodes / classify_transcript / generate_proxies ...）
├── db.py            ← SQLite（dramas / tasks / task_segments / index_entries）
└── tts_engine.py    ← MiMo TTS
```

### 前端（React + Vite, 端口 3000）

页面：`Home`（项目）、`DataDesk`（数据台）、`ScriptDesk`（脚本台：方案全文 + 编辑 + 配音面板）、`VibeEdit`（分镜台：PR 风格源检视器 + 时间轴 + clip↔大纲联动）。

### 关键依赖

| 依赖 | 用途 |
|---|---|
| FastAPI + Uvicorn | HTTP 层（SSE 流式） |
| DeepSeek API | 脚本生成 / 场记 Agent / 分镜推荐 |
| MiMo API | VLM 画面分析 + TTS 配音 |
| BGE（bge-base-zh-v1.5） | 语义嵌入，29854 条 × 768 维 |
| faster-whisper | 口播 ASR（电视剧 v3.1 改走网上下载 SRT 字幕） |
| ffmpeg | 代理视频 / 抽帧 / 切片 |
| numpy | 向量检索（np.dot + argsort，不依赖向量数据库） |

## 四、核心功能模块

### 1. 数据台 — 电视剧数据管线 v3.1（VLM 三层推理 + 情绪锚定）

```
字幕(SRT下载) → DeepSeek 场记Agent 生成 scene_map(人物+地点+事件+情绪)
             → VLM 画面分析（scene_map mood 锚定，1/3+2/3 位置采帧）
```

**v1.3 → v3.1 的优化**：VLM 调用 241次→10-25次/集（↓90%），Token 692K→43K/集（↓94%），情绪矛盾 22→0。**结果**：46 集 1511 个场景，event/mood 完整率 100%。

### 2. 脚本台 — Drama 脚本定稿 v2（单 LLM + 方法论）

**范式转变**：放弃多 Agent 协作（十余轮优化已到瓶颈），改为**单 LLM 一次产出完整脚本**。公网 LLM 对老流行剧的知识比自建 ASR 更可靠。

```
选题 → DeepSeek(SCRIPT_V2_PROMPT) → 完整脚本(论点+装置+起承转合+名场面function) → 落盘 segments.json
```

方法论浓缩：反常识论点 + 叙事装置 + 起承转合 + 名场面穿插 + 金句不复读 + 剥层升华。

### 3. 配音 — 脚本台内嵌（选段生成 / 试听 / 克隆音色）

```
选中段 → 规则驱动方案(narrative + 1.0x) → MiMo TTS → narr_*.wav + 反写 segments.json
```

预设音色（冰糖/茉莉/苏打/白桦）+ 全局克隆音色（上传参考音频），落盘 tts_meta.json 供分镜台消费。

### 4. 分镜台 — 分镜匹配 v8.5（导演 Agent）

**核心理念**：LLM 是导演，把解说词拆成叙事节拍（beats），为每个节拍生成结构化 shot query，通过 `lib/storyboard_match.py` 多维度评分引擎（剧集锚定 + 人物匹配 + 场景情绪冲突补偿 + 景别 + 地点模糊匹配 + 动作滑窗）在 46 集 VLM 缓存中找到最优画面，产出 PRIMARY + SECONDARY 主辅镜头。

### 5. 场景质检漏斗 v4（最新）

视觉切分 + 字幕断裂检测 + 人工兜底，把人工质检量从 1511 降到 12 处——这是最近一个重要的工程里程碑。

## 五、知识库体系（三位一体中的"知识"）

`knowledge/` 是一个 **Obsidian 库**，按 7 层覆盖 **AI 应用开发全链路**：

| 层 | 主题 | 示例笔记 |
|---|---|---|
| L1 | 语言与运行时 | **Python 系列（刚补完）**、JavaScript/React、Shell+ffmpeg |
| L2 | 后端基础设施 | HTTP/SSE、SQLite |
| L3 | AI 基础层 | Embedding、ASR、LLM、VLM、模型部署 |
| L4 | RAG 体系 | 向量检索、混合搜索、BGE 实战 |
| L5 | Agent 系统 | Agent 核心、LangGraph、工具/MCP、HITL |
| L6 | 前端工程 | React、Vite、状态管理与 SSE 消费、Elah 视频引擎 |
| L7 | 前沿探索 | Agentic RAG、多 Agent、自我学习 |

**笔记模板统一**：frontmatter + 一句话摘要 + 是什么/为什么/关键概念/**在 VibeCut 中的应用**（每篇锚定真实代码文件+行号）/前置知识/延伸/动手实验。**每篇笔记 = 一节课程**。

**最近刚完成**：Python 基础/数据处理/标准库与并发 3 篇笔记（填补 L1 层断链）+ 全库过时代码引用清理（server.py → main.py/routers/handlers/lib 现行结构）。

## 六、学习策略（方法论想法）

作者认为 AI 时代"代码都是生成的"，所以学习策略是：

- **三层能力**：读代码（看懂/判断对错，主力）> 改代码（指出改哪/验证）> 写代码（交给 AI）
- **三阶段反刍法**：语法骨架（只学 20% 高频概念）→ 项目反刍（拿 VibeCut 自己代码按数据流走一遍，这是大头）→ 难点突击（只深挖卡住的概念如 async/SSE）
- **「够用就行」原则**：不从头系统学 Python，学到能验收 AI 生成的代码为止
- **笔记就是学习机制**（费曼法）：能写出来教会别人才算真懂

## 七、规划与想法

1. **学习路线 5 阶段**（知识库 `_学习路线.md`）：地基 → AI 入门 → RAG 深入 → Agent 开发 → 前沿探索，每阶段有自检问题。
2. **技术演进方向**（已规划/前沿，笔记里已有基础）：
   - **LangGraph**：把流水线用 StateGraph 重写（Node/Edge/ConditionalEdge/Checkpointer）
   - **Agentic RAG**：从固定管线升级为 Agent 自主决定搜什么、搜几次、要不要改写 query
   - **工具定义与 MCP**：把 VibeCut 模块封装为可复用工具
   - **人机协作 HITL**：关键节点 interrupt/审批
   - **多 Agent 协作 / Agent 自我学习**：不同剪辑风格对应不同 Agent，从反馈中改进
3. **商业**：以 VibeCut 为教学案例的"AI 全栈工程师实战培训课程"，知识库笔记直接转化为课程资产。
4. **代码库演进历史**（重要背景）：早期 http.server 单文件（server.py）→ v1.1 重构为 FastAPI（瘦入口 + routers）；多 Agent 脚本 → v2 单 LLM；ASR 本地 whisper → v3.1 网上下载 SRT 字幕。**任何建议都应基于现行架构**（main.py + routers/ + handlers/ + lib/ + cli/），不要引用已删除的 server.py / script_agents.py。
