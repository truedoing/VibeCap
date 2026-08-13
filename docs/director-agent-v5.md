# 导演Agent v8.5 — 分镜锚定引擎

## 概述

导演Agent 是分镜台的核心推理引擎，负责将解说词转化为结构化的分镜方案（PRIMARY+SECONDARY 主辅镜头），并从原剧中匹配最合适的视频片段。

**核心理念 v8**：LLM 是导演，而非搜索查询生成器。它将解说词拆解为叙事节拍（beats），运用六种导演手法（REACTION/FLASHBACK/CONTRAST/CUTAWAY/ARC/CROSS），为每个节拍生成结构化的 shot query，然后通过匹配引擎在 VLM 场景缓存中找到最优画面。

```
解说词 → LLM导演叙事分析 → beats (节拍) + shots (分镜查询)
                              │
                              ▼
                      匹配引擎 (storyboard_match)
                      多维度评分: 剧集 + 人物 + 场景情绪 + 景别 + 地点 + 动作
                              │
                              ▼
                      最优候选镜头 (PRIMARY + SECONDARY)
```

## 数据流

```
前端 VibeEdit/StoryboardSequence
  │
  │  POST /storyboard_suggest
  │  { narration, cover, segment_context, focus_episodes }
  │
  ▼
handlers/storyboard.py        ← 导演Agent 入口
  │
  ├─ _director_agent()
  │   ├─ DeepSeek → { main_char, beats[], shots[] }
  │   ├─ 人物交叉校验 (cover vs LLM)
  │   ├─ PRIMARY 匹配 → lib/storyboard_match.py
  │   └─ SECONDARY 匹配 → 根据角色(REACTION/FLASHBACK/CONTRAST)灵活搜索
  │
  └─ storyboard_suggest()
      ├─ 格式化 suggestions 文本
      └─ Fallback: v3 分层匹配 (_fallback_storyboard_suggest)

lib/vlm_cache.py              ← 46集 VLM 场景缓存懒加载
lib/storyboard_match.py       ← 结构化匹配引擎 (纯函数)
handlers/prompts/director.py  ← DIRECTOR_PROMPT 模板
lib/scene_map.py              ← 场记Agent: scene_map + synopsis 生成
```

## 核心算法

### 1. 叙事节拍拆解 (LLM DeepSeek)

解说词 → 5 种节拍类型:
- **action**: 动作/事件 → 必须有原剧画面
- **emotion**: 情绪/表情 → 需要表情画面
- **context**: 评述/解释 → 不生成分镜，仅留白
- **punchline**: 金句/主题句 → 需情绪强烈画面
- **argument**: 论证/主题句（如"不光X也Y"）→ 拆解为 ≥2 PRIMARY shot

### 2. 导演手法 (v8.1)

| 手法 | 用途 | 搜索策略 |
|------|------|---------|
| REACTION | 人物情绪/反应特写 | 标的集±3 |
| FLASHBACK | 过去关键画面 | prefer_episodes 可跳出标的集 |
| CONTRAST | 对立状态并置 | 全局搜索 |
| CUTAWAY | 空镜留白 | 不匹配画面 |
| ARC | 情绪递进 | intensity_min 递增 |
| CROSS | 交叉剪辑 | note 标注 |

### 3. 匹配引擎评分 (`lib/storyboard_match.py`)

对指定剧集的每个 VLM 场景逐一评分:

| 维度 | 权重 | 说明 |
|------|------|------|
| 跨镜去重 | -30 | 已在前置分镜中使用的场景大幅惩罚 |
| 剧集锚定 | +15/+5/+2 | 三层权重: 承上启下 > 标的集 > 邻近集 |
| 人物匹配 | +15×N | 每个目标人物交叠+15, 无交叠-10 |
| 画面主体验证 | +5/-4 | 主角在 visual_summary 中+5 |
| 场景情绪冲突检测 (v8.5) | +8 | scene_map mood 高冲突但 VLM 低能情绪 → 补偿 |
| 情绪关键词命中 | +8×N | 目标情绪词在 desc 中 |
| 强度匹配 | (int-min+1)×3 | 有效强度≥要求即加分 |
| 景别匹配 | +6/+5-dist | 精确匹配+6, 距离补偿 max(0,5-dist) |
| 地点匹配 | +4/+3 | 双向子串 + 去后缀模糊匹配 |
| 动作匹配 | +4/+2 | 步长1的2字+3字滑窗 |

### 4. 情绪冲突补偿 (v8.5)

**问题**: VLM 关键帧采样偏差导致高冲突场景被误标为低能情绪。

**修复**: 当 scene_map mood (DeepSeek 从对话推断) 标记为"激烈/愤怒/冲突"等，但 VLM 输出"温和/平静/关切"等低能情绪时，给予 +8 补偿分 + 强度修正。补偿仅在 location 可关联时触发（防止无关场景靠补偿上位）。

### 5. 开篇/总论点模式 (v8.5.4)

当解说词为视频开篇总论点且 focus_episodes 包含多个剧集时，LLM 强制为每个标的集生成独立 PRIMARY shot，直接从 context 中提取已有事件作为查询目标。

## 数据依赖

| 数据文件 | 路径 | 用途 |
|----------|------|------|
| scene_map.json | sources/ep{N}/ | DeepSeek 场记Agent 生成: 场景-人物-事件-情绪-时间 |
| vlm_seg_cache_v3.json | sources/ep{N}/ | MiMo VLM 画面分析: visual_summary, shot_size, emotional_tone, intensity, actions |
| ep_synopsis.json | sources/ep{N}/ | DeepSeek 剧情概要 (注入 LLM 上下文) |
| asr_result.json | sources/ep{N}/ | faster-whisper ASR 转写 (dialogue_match 台词锚定) |

## VLM 管线优化 (v8.5)

### 关键帧采样
- **v8.5前**: 取场景首尾帧 → 切点边界处画面不稳，常错过高潮动作
- **v8.5后**: 取 1/3 + 2/3 位置 → 覆盖场景核心内容

### 情绪锚定
- VLM prompt 注入 scene_map mood 作为情绪基调提示
- "emotional_tone 和 intensity 必须反映这个情绪基调，不能输出相反的温和情绪"

### MiMo v2.5 推理模型适配 (v8.5.6)
- **问题**: MiMo v2.5 是推理模型，`reasoning_content` 字段占满 token，`content` 常为空 → 大量"NoneType object is not iterable"错误
- **修复**: content 为空时 fallback 到 `reasoning_content`；max_tokens 1200→4000

### 抽帧缺失修复 (v8.5.6)
- **问题**: `pick_keyframes_for_segment` 的 `n==0` 分支（场景时间范围无帧命中）忘记 `return`，函数返回 None → `for f in seg_frames` 报 NoneType
- **修复**: `n==0` 分支补上 `return`

### 帧目录误删修复 (v8.5.6)
- **问题**: `analyze_episode` 每次传 `--proxy` 都 `rmtree(frames)` 强制重新抽帧，并发时 ffmpeg 同时写磁盘导致 180s 超时
- **修复**: 移除强制删帧，复用已有帧

### ASR 人名标准化 (v8.5.6)
- **问题**: whisper 转写同音字误识别人名（朱莉→朱丽 107次、明诚→明成 107次、宋明成→苏明成等），污染 scene_map 和下游 Agent
- **修复**: 新建 `cli/normalize_asr_names.py`，全量扫描修复 46 集共 326 处误识别
- **scene_map prompt 加人名归一化铁律**: 要求 DeepSeek 输出 characters 时纠正误识别写法，绝不照抄

### 场记Agent (`lib/scene_map.py`)
- DeepSeek 读取 ASR + 概要 → scene_map
- 时间连续性检查 → >120s 空隙自动补漏
- 降级: 关键词规则 fallback

## 代码架构

```
vibecut-server/
├── handlers/
│   ├── dialogue.py          (184行) — dialogue_match + chat
│   ├── storyboard.py        (581行) — 导演Agent + 分镜推荐
│   ├── prompts/
│   │   └── director.py      (150行) — DIRECTOR_PROMPT 模板
│   └── search.py            (485行) — BGE语义搜索 + ASR锚定搜索
├── lib/
│   ├── vlm_cache.py         (111行) — VLM 场景缓存加载
│   ├── storyboard_match.py  (195行) — 结构化匹配引擎
│   └── scene_map.py         (198行) — 场记Agent
├── analyze_episodes.py      (592行) — VLM 管线 (抽帧/VLM分析)
└── main.py                  (847行) — FastAPI 路由
```

## API

### POST /storyboard_suggest

请求: { narration, cover, segment_context, focus_episodes, num }

响应: { suggestions[], shots[], main_char, beats[], focus_eps[], reasoning }

### POST /dialogue_match

请求: { dialogue }

响应: { lines[] } — 第一句锚定 ASR，无需 LLM 拆解

## 版本迭代

| 版本 | 改动 | 效果 |
|------|------|------|
| v8.5.6 | MiMo推理模型适配 + 抽帧/帧目录/人名标准化修复 | 46集VLM全完成, 空响应452→17, 情绪矛盾→0 |
| v8.5.5 | dialogue_match 第一句锚定 + cluster scoring | 台词定位 0ms (无 LLM 调用) |
| v8.5.4 | 开篇/总论点多剧集 PRIMARY 分配 | 总论点镜头覆盖多事件 |
| v8.5.3 | LLM prompt: 已知地名 + 核心动作词 | 查询更贴合 VLM 数据 |
| v8.5.2 | action 匹配: 步长1滑窗 | "打架" 等词不会因滑窗步长遗漏 |
| v8.5.1 | VLM 抽帧 + mood 锚定 + 情绪冲突补偿 | 3集零情绪矛盾, EP41 持刀场景修复 |
| v8.5 | scene_map mood 补偿 + 跨镜去重 + 画面验证 | 基础分镜匹配 |
| v8.4 | 三层剧集权重 + Agent推理过程 | 标的集内优先匹配 |
| v8.1 | 开篇模式 + 导演手法扩展 | 6种导演手法 |
| v8 | 导演Agent: beats + PRIMARY/SECONDARY | 叙事驱动分镜 |

## 待办: ep_synopsis 结构化升级

**背景**: 当前 ep_synopsis.json 是 400-600 字剧情简介文本，格式混乱（EP41半结构化 vs 其他散文式），且塞入了本属 scene_map 的细粒度字段（location/characters/time_range），职责越界。

**方向**: 升级为结构化宏观叙事索引（JSON），与 scene_map 分工：
- scene_map 保持逐场景细粒度（location/characters/event/mood）
- synopsis 聚焦宏观叙事（主题/人物弧线/情感曲线/关键冲突/关键事件时间锚）

**目标结构草案**:
```json
{
  "theme": "本集核心主题",
  "plot_arc": "起承转合概括",
  "character_arcs": [{"character":"苏明成","arc":"...","relations_change":["与苏明玉和解"]}],
  "key_conflicts": ["父子冲突"],
  "emotional_curve": ["紧张","冲突","和解"],
  "key_events": [{"event":"苏明成持刀阻婚","time_range":[450,570]}]
}
```

**下游影响**: handlers/storyboard.py + agents/drama_script_agents.py 需从读纯文本改为读结构化字段。

**关键约束**: key_events 的 time_range 要能映射到 scene_map；人名标准化铁律继续生效。
