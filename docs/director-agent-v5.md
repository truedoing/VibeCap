# 导演Agent v5 — 分镜锚定引擎

## 概述

导演Agent 是分镜台的核心推理引擎，负责将解说词转化为结构化的分镜方案，并从原剧中匹配最合适的视频片段。

**核心理念**：解说脚本具有天然的三层结构——前后段的高亮台词引用原剧对话（ASR锚定），中间的解说词承上启下。利用这个结构可以大幅缩小搜索空间，提高匹配精度。

```
前段高亮(原剧台词) ──→ ASR关键词匹配 ──→ 锚定剧集 EP_N
     │
     ▼
当前解说词(桥接) ──→ LLM导演理解 + synopsis ──→ 结构化分镜查询
     │
     ▼
后段高亮(原剧台词) ──→ ASR关键词匹配 ──→ 锚定剧集 EP_N+1
```

## 数据流

```
前端 VibeEdit/StoryboardSequence
  │
  │  POST /storyboard_suggest
  │  { narration, cover, prev_highlight, next_highlight,
  │    segment_context: { seg_id, sentences } }
  │
  ▼
后端 storyboard_suggest() [handlers/dialogue.py]
  │
  ├─ Step 0: ASR台词锚定 _anchor_highlight_episodes()
  │     ├─ 2-4字滑动窗口 × 46集ASR
  │     ├─ 前段高亮 → 锚定剧集 EP_prev
  │     └─ 后段高亮 → 锚定剧集 EP_next
  │
  ├─ Step 0.5: 加载锚定剧集剧情概要 ep_synopsis.json
  │
  ├─ Step 1: LLM导演推理 (DeepSeek)
  │     ├─ 输入: 解说词 + cover + 角色出场统计 + 剧情概要 + 锚定信息
  │     ├─ 输出: { main_char, shots: [{ purpose, characters, shot_size,
  │     │           emotional_tone, intensity_min, location_hint,
  │     │           action_hint, prefer_episodes, match_type }] }
  │     └─ match_type: narrative(叙事性) vs character(表现性)
  │
  ├─ Step 2: 人物交叉校验
  │     └─ cover中的人物 > LLM推断, 修正所有分镜的 characters
  │
  └─ Step 3: 结构化匹配 _match_shot_query()
        ├─ 遍历指定剧集的VLM场景缓存
        ├─ 多维度评分: 剧集锚定 + 人物 + VLM画面 + 情绪 + 强度 + 景别 + 地点 + 动作
        ├─ 分镜级剧集分配 (前两镜→prev_ep, 后一镜→next_ep)
        ├─ 跨镜去重 (used_scene_keys)
        └─ 降级: 无结果→放宽景别/场景→去掉剧集限制→全量保底
```

## 核心算法

### 1. ASR台词锚定 (`_anchor_highlight_episodes`)

```
输入: prev_highlight (前段高亮台词), next_highlight (后段高亮台词)
输出: { prev_ep, next_ep, focus_eps, anchor_text }

算法:
  对每句高亮台词:
    1. 去标点, 提取2-4字滑动窗口作为关键词
    2. 过滤停用词 (你想/什么/怎么/还是...)
    3. 遍历46集ASR, 计算每集的关键词命中总分
    4. 取最高分剧集作为锚定结果
    5. 阈值: best_score > 10 视为命中

性能:
  - 46集 × ~700条/集 ≈ 32000条ASR记录
  - 纯字符串匹配, <50ms完成
```

### 2. 结构化匹配评分 (`_match_shot_query`)

对指定剧集的每个 VLM 场景逐一评分:

| 维度 | 权重 | 说明 |
|------|------|------|
| 跨镜去重 | -30 | 已在前置分镜中使用的场景大幅惩罚 |
| 剧集锚定 | +15/+6 | narrative强约束, character弱偏好 |
| 非锚定惩罚 | -8/0 | narrative换集就错, character可灵活 |
| 人物匹配 | +15×N | 每个目标人物交叠+15, 无交叠-10 |
| VLM画面补偿 | +6→+5→+2 | 主角在visual_summary中出现但不在characters中 |
| 画面主体验证 | +5/-4 | VLM描述了主角+5, 主角在场但未描述-4 |
| 情绪匹配 | +8×N | 每个情绪标签命中+8 |
| 强度匹配 | +(intensity-min+1)×3 | 强度不低于要求即加分 |
| 景别精确匹配 | +6 | 精确匹配+6, 距离越远分数越低 |
| 地点提示匹配 | +4 | location_hint 在 scene_locations 中 |
| 动作提示匹配 | +4 | action_hint 在 actions 或 visual_summary 中 |
| 描述丰富度 | +2 | visual_summary > 30字 |

### 3. 分镜类型自适应 (v5.1)

```
narrative (叙事性分镜):
  - 适用: 锚定特定事件/冲突 (如"打架桥段", "拍桌冲突")
  - 锚定策略: 强约束, anchor_bonus=+15, penalty=-8
  - 降级: 不触发全局重搜, 保持锚定

character (表现性分镜):
  - 适用: 表现人物特质/情绪状态 (如"愤怒特写", "冷漠眼神")
  - 锚定策略: 弱偏好, anchor_bonus=+6, penalty=0
  - 降级: 锚定内最高分 < 20 → 全局对比, 全局分高出4分即替换
```

### 4. VLM画面人物补偿 (v5.3)

**问题**: scene_map.json 的 characters 字段只包含有 ASR 台词的人物。无台词出场的角色（仅通过VLM画面识别）会被漏标。

**修复**: 当 visual_summary 中明确描述了主角名，但 scene_map characters 中没有他时:
```
has_main_in_visual:
  → 人物匹配补偿 +6 (替代原本的 -10 惩罚)
  → 画面验证 +5 (原逻辑保留)
  → 漏标补偿 +2 (额外)
  → 总计 +13 (vs 之前在此类场景中得分约 -10-4 = -14)
```

## 数据依赖

| 数据文件 | 路径 | 用途 |
|----------|------|------|
| scene_map.json | sources/ep{N}/ | 场景元数据: characters, event, mood, location, time_range |
| vlm_seg_cache_v3.json | sources/ep{N}/ | VLM视觉分析: visual_summary, shot_size, emotional_tone, intensity, lighting, actions |
| ep_synopsis.json | sources/ep{N}/ | DeepSeek生成的剧情概要 (v5.2+) |
| asr_result.json | sources/ep{N}/ | ASR转写, 用于高亮台词锚定剧集 |

## API

### POST /storyboard_suggest

**请求**:
```json
{
  "narration": "解说词文本",
  "cover": "苏明成/炸弹视角",
  "num": 3,
  "prev_highlight": "前段高亮台词",
  "next_highlight": "后段高亮台词",
  "segment_context": {
    "seg_id": 5,
    "sentences": ["解说词切句1", "解说词切句2"]
  }
}
```

**响应**:
```json
{
  "suggestions": ["镜头1: ... | EP41 [2070s] ... [中景]", ...],
  "shots": [
    {
      "purpose": "展现苏明成持刀威胁的狂态",
      "query": {
        "characters": ["苏明成"],
        "shot_size": "中景",
        "emotional_tone": ["冲突", "愤怒"],
        "intensity_min": 4,
        "location_hint": "苏大强家客厅",
        "action_hint": "苏明成手持菜刀...",
        "prefer_episodes": [41],
        "match_type": "narrative"
      },
      "candidates": [
        {
          "ep": 41,
          "start": 2070,
          "end": 2130,
          "visual_summary": "苏明成在办公室双手合十...",
          "shot_size": "中景",
          "emotional_tone": "焦虑恳切",
          "intensity": 3,
          "location": "苏明玉办公室",
          "characters": ["苏明玉", "苏明成", "朱丽"],
          "match_score": 43
        }
      ]
    }
  ],
  "main_char": "苏明成",
  "anchor": {
    "prev_ep": 41,
    "next_ep": 39,
    "focus_eps": [39, 41]
  }
}
```

## 关键文件

| 文件 | 内容 |
|------|------|
| vibecut-server/handlers/dialogue.py | 导演Agent核心: director_agent(), _match_shot_query(), _anchor_highlight_episodes(), 两个prompt模板 |
| vibecut-server/main.py:546 | POST /storyboard_suggest 路由 |
| vibecut-web/src/components/StoryboardSequence.jsx | 前端分镜面板: 提取前后段highlight_text, 发送请求, 渲染分镜卡片 |
| vibecut-web/src/components/ScriptPanel.jsx | 脚本面板: highlight_text(台词) + narration_text(解说) 双行渲染 |
| vibecut-web/src/pages/VibeEdit.jsx | 分镜台主页: 管理segments, curNarration, storyTrigger |

## 版本迭代

| 版本 | 改动 | 效果 |
|------|------|------|
| v4 | 初始导演Agent: LLM叙事理解 + scene_map匹配 | 基础分镜功能 |
| v5 | +ASR台词锚定剧集 + 跨镜去重 + 画面主体验证 | 前后段锚定命中, 分镜不重复 |
| v5.1 | +match_type (narrative/character) 自适应锚定权重 | 叙事性强约束, 表现性灵活全局搜索 |
| v5.2 | +ep_synopsis.json注入LLM上下文 | LLM理解真实剧情, 不再凭空编造场景 |
| v5.3 | +VLM画面人物补偿 (visual_summary中的角色) | 无台词出场人物场景不再被误惩罚 |
| v5.3b | +_chars合并到characters (从vlm_seg_cache_v3加载) | scene8派出所/打架场景从漏标修复为完整标注, 镜头2 TOP1命中派出所 |
| v5.2 | +ep_synopsis.json注入LLM上下文 | LLM理解真实剧情, 不再凭空编造场景 |
| v5.3 | +VLM画面人物补偿 (visual_summary中的角色) | 无台词出场人物场景不再被误惩罚 |
