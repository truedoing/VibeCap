# VIBECAP 更新日志

## v0.11.0 — 数据增强管线 + 故事优先流水线 (2026-08-03)

### 数据台
- **clean_interview_data.py**: LLM 文本清洗 + 说话人识别。批量处理 classified ASR，每批25句。输出 `classified_enhanced.json`（新增 `cleaned_text` + `speaker` 字段）。299句 guest / 168句 host / 38句文本修正，耗时88s。
- **build_interview_index.py**: 口播采访 BGE 索引重建。优先使用 enhanced 数据，speaker 边界断开分块（不同说话人不合并），只用 guest 句子建索引，用 `cleaned_text` 编码、`original_text` 展示。索引从 73 条（含主持废句）→ 66 条（纯嘉宾内容，零污染）。
- **classify_transcript.py**: LLM 口播 ASR 分类（content/meta/guide/filler 四层）
- **segment_transcript.py**: LLM 采样 + 主题分段（5-8 组观点单元）

### 策划台
- **PlanningDesk.jsx**: 策划台重构，AI 生成脚本 SSE 流式进度 + 日志面板
- **故事优先流水线 (story-first v4)**: LLM 通读全部 ASR → 理解完整故事 → 一次性输出分组段落脚本
  - 分组段落结构 `section(clips, 2-5个)`，段落内保留原文"第一/第二/第三"逻辑
  - 过渡句全部来自 ASR 原文（0 句 AI 生成），找不到过渡就硬切
  - 单次 LLM 调用 ~12s 完成（对比 v3 搜索流水线 ~40s）
  - API: `POST /script/generate_story_first`
- **v3 搜索流水线 (run_pipeline)**: 策划师 → 文案师(BGE) → 精编师(LLM) → 审核师(LLM)
  - 全局时间跟踪（搜索阶段偏好冷门窗口）+ 邻近检测（8s）+ 桶限制（≤2/窗口）
  - 口语废句源头过滤（12 条正则 + 嵌入废词清理）
  - 强 topic 锚点（evidence/proof ≥2 关键词）
  - 累积式修复（时间堆砌 + 收尾 + 漂移 + 素材不足 同时修）

### Server
- BGE 离线模式（`HF_HUB_OFFLINE=1`）：模型加载 194s → 8s
- 搜索返回 `original_text`（ASR 原文）+ `cleaned_text`（清洗后）
- `.env` 空值覆盖修复：空环境变量不再阻止 `.env` 加载
- 新增端点：`POST /script/generate_story_first`、`GET /tasks/文案脚本.json`
- 回调函数返回 list/dict 防御

### 修复
- `_call_llm` 双重 `urlopen` bug
- 搜索循环 `r = q.get()` 覆盖策划结果
- LLM 返回 list 型 JSON 崩溃
- 流水线返回缺少 `rich_count`/`final_count`/`total`
- 策划台 SSE 双重 `JSON.parse`

---

## v0.10.0 — 沉浸剪辑台 (2026-08-02)

- 源定位器 + 分镜推荐 + 剧集优先搜索
- VibeEdit.jsx 沉浸剪辑台（策划+剪辑合并）

## v0.8-0.9 — VLM 优化流水线

- VLM 并发 4→12→20，单集 32min→6.5min
- 540p 代理视频，帧提取 3x 加速
- VLM 场景智能合并，冗余 -15%

## v0.7 — 多任务架构

- 加权 n-gram + 繁简归一化 ASR 匹配
- `?task=` 参数，一个 server 服务所有任务
