# VibeCut 变更日志

## v1.2.0 (2026-08-12) — 编剧Agent: Drama脚本生成 (MINOR)

### 新增

#### 编剧Agent v1 — Drama 脚本生成系统

**核心理念**: 打破 docx 导入的半手工链路，用 AI Agent 直接创作带精确画面引用的解说脚本。三个独立 Agent 角色协作，人提供创意方向（选题+选集+时长），Agent 负责执行。

**三个Agent角色**:
- **故事师** (`story_master_agent`) — 通读46集剧情概要，提取人物弧光/转折点/高光场景/选题建议
- **策划师** (`narrative_planner_agent`) — 故事地图+选题 → 4-7章叙事方案（含场景锚点+导演手法+时长估算）
- **文案师** (`script_writer_agent`) — 章节+scene_map → 解说词+scene_query（含highlight_text原剧台词）

**7层写作结构**:
1. 核心视角 — 每章聚焦单一人物/主题
2. 开场钩子 — ≤50字观点句，3秒抓住注意力
3. 原剧台词 — highlight_text作为"原声证据"
4. 解说节奏 — 钩子→背景→事件→高潮→升华
5. 语言风格 — 网感+幽默+金句，禁止干巴复述
6. 人物心理 — 分析动机，不只讲"发生了什么"
7. 结尾金句 — 价值观升华，制造共鸣和转发欲

**审核策略**: 程序校验替代LLM审核（scene_query与scene_map精确匹配，修正time_range偏移，0 LLM调用节省约70s）

**新增文件**:
- `drama_script_agents.py` — 三个Agent + 编排器 `run_drama_pipeline()` + 程序校验
- `handlers/script_drama.py` — SSE端点处理函数
- `handlers/prompts/script_drama.py` — 编剧Agent Prompt模板（故事师/策划师/文案师/审核师）

**新增API**:
- `POST /script/generate_drama_script` — 编剧Agent SSE端点
  ```json
  {"topic": "苏明成人物线", "episodes": [1,3,21,39,41,45], "target_duration": 240}
  ```

**产出格式**: segments.json（兼容VibeEdit/ScriptPanel/Storyboard），新增字段：
- `scene_query`: {episode, time_range, characters, location, event, mood, shot_size_hint, intensity}
- `source_start`/`source_end`: 精确视频时间戳（从scene_map直接获取，无需locate_clips.py模糊匹配）
- `episode_marker`: 剧集锚点（向下兼容）

### 修改

#### 数据质量
- **46集scene_map全部重建**: 1511个场景，event/mood/location/characters 完整率100%
- **scene_map生成优化**: `lib/scene_map.py` — 强化event/location/mood不可为空约束 + 重试机制 + 分批批处理 + 补漏修复
- **数据台评分重算** (`/data/quality`): 四维度评分体系 ASR25% + VLM30% + scene_map30% + synopsis15%
- **DataDesk.jsx**: 前端显示新增 `scene_map_score` 和 `synopsis_score`

#### 任务管理
- **支持无docx创建任务** (`handlers/tasks.py`): 新任务不再强制要求上传解说文案，可直接由AI编剧生成

#### 前端
- **PlanningDesk.jsx** — drama模式UI:
  - 左栏: 选题描述textarea + 时长滑块 + 剧集多选网格(1-46) + 快速范围按钮
  - 中栏: SegmentCard显示scene_query信息 (episode/location/event/mood/intensity) + 钩子标记
  - 右栏: AI进度日志 + 生成结果摘要
  - interview/drama自动切换 (通过projectName检测)
- **DataDesk.jsx**: 四维度质量分显示 + 修复ep_number→ep字段

### 架构影响

```
四台流水线 v2.5 → v3.0:
  项目 → 数据台 → 编剧台 → 分镜台 → 剪映
          ✅        ✅✨      ✅        ✅
          
编剧台补齐了drama方向的AI创作能力:
  interview: v3/v4 pipeline (从ASR选句编排)
  drama:    编剧Agent v1 (从scene_map创作脚本)
```

---

## v2.5 (2026-08-10)

### 导演Agent (分镜台)
- **v8.5.5**: dialogue_match 第一句锚定 + cluster scoring (台词定位0ms, 无LLM调用)
- **v8.5.4**: 开篇/总论点多剧集 PRIMARY 分配 (总论点镜头覆盖多事件)
- **v8.5.3**: LLM prompt: 已知地名 + 核心动作词 (查询更贴合VLM数据)
- **v8.5.2**: action 匹配: 步长1滑窗 (修复"打架"等词遗漏)
- **v8.5.1**: VLM 抽帧 + mood 锚定 + 情绪冲突补偿 (3集零情绪矛盾, EP41持刀场景修复)

### 架构重构
- `lib/scene_map.py` — 提取场记Agent (从analyze_episodes中分离)
- `lib/storyboard_match.py` — 纯函数匹配引擎 (独立可测试)
- `lib/vlm_cache.py` — VLM场景缓存懒加载 (供storyboard/search共用)
- `lib/llm.py` — 统一LLM调用 (消除10种重复实现)
- `lib/sse.py` — 可复用SSE发射器 + 心跳
- `handlers/prompts/director.py` — DIRECTOR_PROMPT模板分离

### 淘汰
- `cross_calibrate.py` — ASR↔VLM交叉校准 (scene_map已替代)
- `vlm_char_calibrate.py` — VLM人物校准T1-T4 (VLM不再认人)

---

## v2.0 (2026-08-08)

### 四台流水线正式定型
- 项目台: 制片 (选项目, 管进度)
- 数据台: DIT (建索引, 跑管线)
- 编剧台: 编剧 (写解说词, 生成脚本)
- 分镜台: 导演/分镜师 (解说词→镜头匹配)

### 产品定位正规化
- 从"剪辑台"到"导演台"的概念升级
- 产品名称: VibeCut (原VibeCap)

---

## v1.3 (2026-08-05)

### 数据管线优化
- VLM调用量 ↓90% (241→10-25次/集)
- Token消耗 ↓94% (692K→43K/集)
- 关键帧采样: 首尾帧→1/3+2/3位置
- 人物识别: VLM认人脸(~29%错误)→scene_map确定(0%错误)

### 三层推理管线
1. DeepSeek 场记Agent → scene_map
2. ASR 关键词锚定 → 精准时间边界
3. VLM 画面理解 → mood锚定+结构化JSON

---

## v1.1 (2026-08-03)

### 架构重构
- FastAPI 迁移 (server.py 2,866行→模块化架构)
- 模块化拆分: handlers/ + lib/
- 统一SSE协议: `_sse_gen()` 通用包装器
- 统一LLM调用: `lib/llm.py`

### 编剧台 v3/v4
- v3: 搜索流水线 (策划师→文案师→精编师→审核师, 累积式修复)
- v4: 故事优先 (口播专用, LLM通读全ASR→一次性输出)

---

## v1.0 (2026-07)

### 初始版本
- 基础四台流水线原型
- BGE语义索引 (29,797×768维)
- docx→segments.json解析 (`parse_docx.py`)
- 剪映草稿导出
- React前端 (Vite, 三栏布局)
