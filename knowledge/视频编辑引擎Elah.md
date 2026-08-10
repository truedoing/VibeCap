---
title: 视频编辑引擎Elah
type: topic
tags: [framework, technique, implemented]
difficulty: 中等
prerequisites: ["React与Vite", "ffmpeg媒体处理"]
status: implemented
created: 2026-08-04
---

# 视频编辑引擎 Elah

> `@elah/editor`：一个运行在浏览器里的 NLE（非线性编辑）引擎。VibeCut 用它在网页里实现多轨时间轴、预览播放和素材管理。

## 是什么

**Elah** 是一套浏览器端视频编辑 SDK，核心包包括：

| 包 | 功能 |
|---|---|
| `@elah/editor` | 主入口：EditorProvider、Preview、Timeline、MediaLibrary |
| `@elah/core` | 核心引擎：时间轴模型、导出管线 |
| `@elah/timeline` | 时间轴 UI 组件 |

它不是传统桌面软件（如 Premiere、剪映），而是一个**纯浏览器的 NLE 引擎**——所有渲染在 WebGL2 上完成，不需要安装任何软件。

## 为什么用浏览器 NLE

| 传统桌面剪辑 | 浏览器 NLE (Elah) |
|---|---|
| 安装软件 + 学习成本 | 打开网页即用 |
| 剪辑结果本地文件 | 数据随时同步到后端 |
| AI 集成困难（插件机制） | AI 原生集成（API 直连） |
| 文件管理手动 | 代理视频自动从服务端拉取 |
| 无法远程协作 | 同一份数据多人查看 |

对于 VibeCut 的场景——AI 搜索素材 → 自动建轨 → 人类微调 → 导出——浏览器 NLE 是最自然的形态：AI 生成的剪辑数据直接喂给时间轴，人类在网页上审核和微调。

## 关键概念

### 1. 核心 API

```jsx
import {
  EditorProvider,     // 编辑器上下文（包裹所有子组件）
  Preview,            // WebGL2 视频预览画布
  Timeline,           // 多轨时间轴 UI
  createDefaultDemuxerFactory,  // 解封装器工厂（解析视频文件）
  useTimelineEngine,  // 引擎 hook：loadProject / addClip / removeClip
  useTracksStore,     // 轨道状态
  usePlaybackStore,   // 播放状态
  useMediaLibraryStore, // 素材库状态
  secondsToFrames,    // 时间转换工具
  generateId,         // ID 生成
} from '@elah/editor'
```

### 2. Project 数据结构

每个 Elah 项目是一个 JSON 对象：

```js
{
  id: 'vibecut-prg',
  fps: 25,
  stage: { width: 1920, height: 1080 },
  tracks: [
    { id: 'track-1', name: '原声主镜头', kind: 'video', order: 2, height: 52 },
    { id: 'track-2', name: '原声主镜头 音频', kind: 'audio', order: 0, height: 44 },
  ],
  clips: {
    'track-1': [
      { id: 'clip-1', trackId: 'track-1', type: 'video',
        src: '/proxies/file.mp4', startFrame: 0, durationFrames: 250,
        sourceStartFrame: 125, sourceDurationFrames: 250 }
    ],
    'track-2': [...]
  },
  transitions: [],
  version: 1,
  masterVolume: 1,
}
```

关键点：`startFrame` 是时间轴上的位置，`sourceStartFrame` 是源视频中的起始位置。通过这两个值，同一段源素材可以出现在时间轴的不同位置。

### 3. Demuxer 工厂

```jsx
const demuxRef = useRef(createDefaultDemuxerFactory())
// 传给 EditorProvider，用于解析代理视频文件
```

Demuxer（解封装器）负责解析视频文件的容器格式（MP4），分离出视频流和音频流。`createDefaultDemuxerFactory` 会在后台创建 Web Worker 线程来解码，不阻塞 UI。

### 4. 双轨道模式

VibeCut 根据项目类型使用不同的轨道布局：

```
口播 (interview):                     电视剧 (drama):
┌─────────────────────┐              ┌─────────────────────┐
│ 原声主镜头 (video)   │              │ 补充镜头 (video)    │ ← 静音
├─────────────────────┤              ├─────────────────────┤
│ 原声 音频 (audio)    │              │ 原声主镜头 (video)   │
└─────────────────────┘              ├─────────────────────┤
                                     │ 原声 音频 (audio)    │
                                     ├─────────────────────┤
                                     │ 旁白 TTS (audio)    │
                                     └─────────────────────┘
```

口播只有 2 轨（主镜头 + 音频），因为口播素材是单一视频源、无需补充镜头和旁白。电视剧有 4 轨，完整支持解说视频的剪辑需求。

### 5. 媒体库与资产注册

```js
// 注册媒体资产（必须先注册才能加到时间轴）
const store = useMediaLibraryStore.getState()
store.addAsset({
  assetId: 'asset-1',
  src: '/proxies/file.mp4',
  name: 'S1 EP01 主',
  kind: 'video',
  durationSec: 12.5,
})
```

流程：加载代理视频 URL → 注册到 MediaLibrary → 创建 clip 加到时间轴轨道。缺少任何一步，时间轴上都会显示空白。

## 在 VibeCut 中的应用

**`VibeEdit.jsx`**（分镜台）是 Elah 的主要消费者：

1. **初始化**：检测项目类型（口播/电视剧）→ 创建对应轨道布局 → `engine.loadProject()`
2. **自动建轨**（口播）：`segments` 到达后 → `buildProjectFromProxyPicks()` 构建项目 → 加载到 engine → 持久化缓存
3. **缓存恢复**：刷新页面 → 加载 `vibe_timeline` 缓存 → 比对 track 数是否匹配 → 匹配则直接恢复
4. **自动保存**：监听 `engine.on('change')` → 300ms 防抖 → 保存到 `vibe_timeline`

**`timelineBuilder.js`**：从 picks 数据构建 Elah project，是 VibeCut 业务逻辑和 Elah 数据格式之间的桥梁。

**`proxyEngine.js`**：代理视频 URL 解析，将素材引用（episode + 时间范围）转换为 Elah clip 参数。

## 前置知识

- [[React与Vite]] — Elah 是 React 组件库，需要 React 基础
- [[ffmpeg媒体处理]] — 代理视频需要 ffmpeg 生成

## 延伸

- [[状态管理与SSE消费]] — Elah 内部用 Zustand 管理状态
- [[SQLite数据层设计]] — timeline 缓存持久化

## 动手实验

1. **观察 Project 数据结构**
在分镜台页面打开浏览器 Console，输入：
```js
window.__vibe_prg_engine.getProject()
```
观察返回的 project JSON 结构，特别关注 `tracks` 和 `clips` 字段。

2. **手动加载一段空轨道**
```js
const engine = window.__vibe_prg_engine
engine.loadProject({
  id: 'test', fps: 25, stage: { width: 1920, height: 1080 },
  tracks: [{ id: 't1', name: '测试', kind: 'video', order: 0, height: 52 }],
  clips: { t1: [] }, transitions: [], version: 1, masterVolume: 1
})
```

## 学习资源

- `@elah/editor` 官方文档 — SDK 完整 API 参考
- `VibeEdit.jsx` 源码 — 实际集成的最佳参考
- `timelineBuilder.js` 源码 — Project 数据构建逻辑
