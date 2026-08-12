# VibeCut 配音台设计文档 v1.0

## 概述

配音台 (VoiceDesk) 是 VibeCut 流水线的第五个台位，位于编剧台和分镜台之间。核心任务是将 AI 生成的解说脚本文案转为自然语音。

**设计理念**: AI 配音不是传统的“对口型”，而是“解说脚本的声音化”——先有音频时长，分镜台就能按精确时长配画面。

## 流水线位置

```
项目 ──→ 数据台 ──→ 编剧台 ──→ 配音台 ──→ 分镜台 ──→ 剪映
制片      建索引     写脚本     AI语音     分镜匹配    精剪导出
```

## 配音师 Agent (VoiceDirector)

### 角色定位

一个轻量级 LLM Agent，负责为解说脚本设计配音方案。与编剧台的三个 Agent 不同，配音师无需拆分为多角色——它的核心工作是“理解叙事 → 匹配配音参数”。

### Agent 协议

```
输入: segments[] (narration_text + section_role)
输出: voice_plan[] (emotion + speed + pause_after_ms + emphasize)
```

### 6 种配音情绪

| 情绪 | 英文 | 适用场景 | 语速特征 |
|------|------|---------|---------|
| 悬念 | suspense | 开场 hook、剧情转折 | 略慢 0.9x，压低声音 |
| 叙述 | narrative | 背景 context、过渡 bridge | 标准 1.0x，沉稳自然 |
| 激昂 | passionate | 证据 evidence、高光 highlight | 稍快 0.95x，饱满有力 |
| 分析 | analytical | 人物心理 insight | 标准 0.95x，冷静克制 |
| 温暖 | warm | 收尾 closing、人物弧光 | 较慢 0.85x，娓娓道来 |
| 幽默 | humorous | 梗/段子、反差对比 | 标准 1.0x，轻松活泼 |

### 配音节奏原则

- 开场 hook 应该有力、悬念感强，吸引 3 秒注意力
- 背景说明用平实叙述，信息密集时可稍快
- 高光/证据段要饱满有力，可用稍慢语速强调情绪
- 过渡桥段要自然流畅，不宜过慢
- 收尾要有温暖升华感，适当放慢 + 增加停顿
- 相邻段情绪不应剧烈跳变 (suspense→warm 最远，需加停顿缓冲)

### Fallback 机制

当 LLM 不可用时，自动降级为规则驱动方案：

```
hook_tension → suspense  0.9x  500ms
evidence     → passionate 0.95x 350ms
context      → narrative  1.0x  300ms
bridge       → narrative  1.0x  300ms
insight      → analytical 0.95x 400ms
closing      → warm       0.85x 600ms
highlight    → passionate 0.9x  400ms
```

## 技术架构

### 后端

```
vibecut-server/
├── tts_engine.py                ← 统一 TTS 引擎 (MiMo API)
├── handlers/
│   ├── voiceover.py             ← 配音师 Agent + SSE handler
│   └── prompts/
│       └── voiceover.py         ← 配音师 Prompt 模板
└── main.py                      ← /voiceover/generate_stream 路由
```

### 前端

```
vibecut-web/src/
├── pages/
│   └── VoiceDesk.jsx            ← 配音台页面 (三栏布局)
└── main.jsx                     ← 路由 + 导航标签
```

### API

**`POST /voiceover/generate_stream`** (SSE)

请求体:
```json
{
  "task": "Task0804",
  "voice": "default_zh",
  "speed": 1.0,
  "pause_ms": 300,
  "ref_audio_path": null
}
```

SSE 事件流:
```
event: progress → {"step":"init",           "msg":"🎙️ 配音师就绪 · 15段 · 默认女声"}
event: progress → {"step":"director",        "msg":"🎬 配音师分析脚本 → 设计配音方案..."}
event: progress → {"step":"director_done",   "msg":"✅ 配音方案就绪: 15段"}
event: progress → {"step":"segment_start",   "seg_id":0, "emotion":"suspense"}
event: progress → {"step":"segment_done",    "seg_id":0, "duration":4.7, "done":1, "total":15}
event: progress → {"step":"segment_start",   "seg_id":1, "emotion":"narrative"}
event: progress → {"step":"segment_done",    "seg_id":1, "duration":5.2, "done":2, "total":15}
...
event: complete → {"ok":true, "total_segments":15, "total_duration":234.5}
```

### 音色支持

| ID | 标签 | 说明 |
|----|------|------|
| default_zh | 默认女声 | 清晰自然，通用解说 |
| narrator_male | 沉稳男声 | 低沉有力，悬疑/正剧 |
| narrator_female | 温柔女声 | 温暖柔和，情感向 |
| storyteller_male | 激昂男声 | 饱满有力，高光时刻 |
| (克隆模式) | 自定义 | 上传参考音频克隆 |

## 数据契约

### 输入: segments.json (编剧台产出)

```json
{
  "segments": [
    {
      "seg_id": 0,
      "narration_text": "苏明成终于意识到...",
      "section_role": "hook_tension"
    }
  ]
}
```

### 输出: narration.json

```json
[
  {
    "index": 0,
    "seg_id": 0,
    "start": 0.0,
    "end": 4.7,
    "narration": "苏明成终于意识到...",
    "pause_after_ms": 500,
    "overlaps_speech": false,
    "emotion": "suspense"
  }
]
```

### 输出: tts_meta.json

```json
{
  "engine": "mimo-v2.5-tts",
  "voice": "default_zh",
  "global_speed": 1.0,
  "global_pause_ms": 300,
  "segments": [
    {
      "index": 0,
      "seg_id": 0,
      "start": 0.0,
      "end": 4.7,
      "narration": "苏明成终于意识到...",
      "audio_path": "tts_segments/narr_000.wav",
      "duration": 4.7,
      "pause_after_ms": 500,
      "emotion": "suspense",
      "speed": 0.9
    }
  ],
  "narration": "/path/to/work_dir/narration.json"
}
```

### 输出: tts_segments/

```
work_dir/tts_segments/
├── narr_000.wav (4.7s)
├── narr_001.wav (5.2s)
├── narr_002.wav (3.8s)
...
```

### segments.json 反写

配音完成后，`segments.json` 被更新:
```json
{
  "audio_verified": true,
  "segments": [
    {
      "seg_id": 0,
      "audio_duration": 4.7,
      "audio_path": "tts_segments/narr_000.wav",
      "audio_emotion": "suspense"
    }
  ]
}
```

分镜台加载时可直接使用 `audio_duration` 作为 shot 时长约束。

## 前端界面

三栏布局:

```
┌─────────────────────────────────────────────────────────┐
│  导航：项目 | 数据台 | 编剧台 | 配音台🟢 | 分镜台        │
├──────────────┬──────────────────────┬───────────────────┤
│  音色库       │  脚本段落列表         │  控制台            │
│  (左 220px)  │  (中 flex-1)         │  (右 260px)       │
│              │                      │                   │
│  · 默认女声   │  S0 🎭悬念  ✅4.7s  │  语速倍率 1.0x    │
│  · 沉稳男声   │  苏明成终于意识到... │  [========滑块====] │
│  · 温柔女声   │  [▶ 播放]           │                   │
│  · 激昂男声   │                      │  段间静音 300ms   │
│              │  S1 📖叙述  ⏳待生成  │  [========滑块====] │
│  📤 上传参考  │  从妈宝到守护者...              │
│  音频        │                      │  生成进度          │
│              │  S2 🧠分析  ✅3.8s   │  ████████░░ 8/15  │
│              │  这一切的根源在于... │                   │
│              │  [▶ 播放]           │  [🎙️ 一键生成配音] │
└──────────────┴──────────────────────┴───────────────────┘
```

## 与已有系统的兼容

| 系统 | 兼容方式 |
|------|---------|
| `match_split.py` | tts_meta.json 格式对齐，engine 从 "pre_recorded" 改为 "mimo-v2.5-tts" |
| `timelineBuilder.js` | 已用 `/tts_segments/narr_${sid}.wav` 构建音频 URL，无缝兼容 |
| Vite 代理 | 已配置 `/tts_segments/` → localhost:8765 |
| segments.json | `audio_verified` 字段已预留，本台设为 true |
| `export_capcut.py` | 已有 `_make_audio_material()` 处理音频素材 |

## 已知限制与后续迭代

1. **F5-TTS 未接入**: `f5tts_clone.py` 是离线方案，本次只用 MiMo 云 API
2. **无波形可视化**: 当前用简单 `<audio>` 播放，Web Audio API 波形渲染待后续
3. **无批量 re-generate**: 仅支持单段逐个生成 + 一键全部生成
4. **音色预览**: 预设音色无 sample 试听，需后续添加
5. **分镜台消费**: `audio_duration` 已注入 segments.json，分镜台集成放下个迭代

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-08-12 | 初始实现: 配音师 Agent + MiMo TTS 引擎 + VoiceDesk 页面 |
