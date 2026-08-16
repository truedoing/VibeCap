# 架构变革记录：编剧台从「多 Agent + RAG」回归「公网 LLM 直出」

> 日期：2026-08-16
> 性质：架构级决策，推翻 v1.2.0 ~ v1.3.0 的编剧台多 Agent 方案

---

## 一、结论（先说最重要的）

**文案创作这个任务，用「多 Agent 协作 + RAG 检索」从头就是错的方案。**

文案创作是 LLM 最擅长的领域之一——尤其是对《都挺好》这类公开的老流行剧，公网 LLM 的训练数据里已经吃透了剧情、人物、名场面、台词。我们却绕了一大圈：建 RAG 检索、切 6 个 Agent（故事师/论点师/策划师/文案师/审核师）、造事实卡片、做增量快照、搞 SRT 锚定……结果产出质量反而不如「一段方法论 prompt + 公网 LLM 一次直出」。

**这是方向性错误，不是执行不到位。** 多 Agent 的复杂，恰恰是割裂的来源；RAG 补的"知识"，是公网 LLM 本来就有的知识。

---

## 二、我们走过的弯路（完整时间线，作为反面教材）

| 阶段 | 做了什么 | 结果 |
|---|---|---|
| v1.2.0 | 故事师 + 策划师 + 文案师，多 Agent 协作 | 能跑，但文案"机械化"，一段一个观点卡片 |
| v1.2.x | 加论点师、装置、事实卡片分离（LCAS 借鉴） | 幻觉压住了，但车轱辘话、金句复读反复冒头 |
| v1.3.0 | 论点聚焦、增量快照、原声句、跨章去重…… | 每修一个 bug，冒一个新 bug，打地鼠 |
| v1.4.0 | 单 LLM + 方法论（V2） | **一次直出，质量反超多 Agent** |

关键转折点：用户拿「公开方法论 + 公网 LLM」直接产出的脚本《保姆三句话，骗走一套房》对比，发现它**没用任何 RAG、任何多 Agent**，却比我们调了十几轮的多 Agent 系统还好。

---

## 三、为什么方案从根上就错了

### 1. LLM 本就擅长文案创作

文案创作（讲故事、剥层、金句、名场面）是 LLM 的**核心能力区**。给它一段清晰的方法论（反常识论点、起承转合、名场面穿插、金句克制），它一次就能写好。

### 2. RAG 补的知识，是 LLM 本来就有的

对公开老剧，公网 LLM 训练数据里已经完整包含剧情、人物、台词。我们的 RAG 反而引入了**更差的数据**——whisper ASR 把「图你不洗澡」误识别成「徒你不许打」，比公网 LLM 的记忆还不可靠。

### 3. 多 Agent 的复杂，是割裂的来源

6 个 Agent 串行，每个环节都可能掉链子，且环节之间靠结构化 JSON 传递，信息在传递中损耗。一个 LLM 一气呵成，反而保持了叙事的连贯性。

---

## 四、正确的架构

```
外部工具（扣子 / WorkBuddy）+ 公网 LLM
   ↓ 用方法论 prompt 一次产出完整脚本 JSON
   ↓
VibeCut 接收（建任务上传 / 编辑台导入）
   ↓ 用 SRT 字幕数据做「台词反查 + 时间码校准」（这是 VibeCut 真正的价值）
   ↓
编辑台（查看方案全文 + 微调正文）
   ↓
分镜台 / 配音台（消费 segments.json）
```

**VibeCut 的定位变了**：不再"生成文案"，而是**「接收外部文案 → 校准锚定 → 编辑 → 导出给下游」**。

我们真正的技术壁垒，不是"文案生成"，是：
- SRT 字幕数据（正确的台词 + 精确时间码）
- 下游流水线（分镜匹配、配音、剪映导出）

---

## 五、本次清理范围

删除（多 Agent 时代的产物，全部作废）：

| 模块 | 说明 |
|---|---|
| `agents/drama_script_agents.py` | 故事师/论点师/策划师/文案师/审核师 + run_drama_pipeline |
| `handlers/prompts/script_drama.py` | 多 Agent 的 prompt（STORY_MASTER/THESIS/NARRATIVE/SCRIPT_WRITER/REVIEWER） |
| `handlers/script_drama.py` 的 generate_thesis / generate_drama_script | 多 Agent 入口 |
| `handlers/topics.py` + `routers/topics.py` | 选题推荐（制片/故事师/论点师驱动） |
| `cli/generate_drama.py` + `cli/topic_recommend.py` | 多 Agent 的 CLI |
| 前端 PlanningDesk 的 generateDramaScript/generateThesis/thesis/selectedEps 等死代码 | 生成 UI 已删，代码残留 |

保留：

| 模块 | 说明 |
|---|---|
| `handlers/prompts/script_drama.py` 的 `SCRIPT_V2_PROMPT` | 单 LLM 方法论（V2 的核心，保留） |
| `handlers/script_drama.py` 的 `generate_drama_script_v2` + `_save_*_v2` | 单 LLM 生成 |
| `routers/sse_script.py` 的 `/generate_drama_script_v2` | 单 LLM 端点 |
| `cli/parse_external_json.py` | 外部 JSON 解析 |
| SRT 字幕 + subtitle_result.json | 数据底座（真正的价值） |

---

## 六、教训（提炼成方法论，供后续决策）

1. **先问"这任务是不是 LLM 本就擅长的"** —— 是，就别上 RAG/多 Agent，直接给方法论 + 公网 LLM。
2. **RAG 的价值边界** —— RAG 补的是「LLM 训练数据里没有的私有/实时知识」，不是「LLM 本来就有的公开知识」。用错地方，RAG 是负资产。
3. **多 Agent ≠ 更好** —— 多 Agent 适合「任务可分解、步骤有明确输入输出、需要工具调用」的场景；不适合「创意连贯性优先」的文案创作。环节越多，割裂越重。
4. **数据质量是根基** —— 我们的 ASR 不如公网 LLM 的记忆可靠，这不是 LLM 的问题，是我们的数据管线问题（已用 SRT 字幕替换）。
