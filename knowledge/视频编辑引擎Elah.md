---
title: 视频编辑引擎Elah
type: topic
tags: [framework, technique, implemented]
difficulty: 中等
prerequisites: ["React与Vite", "JavaScript与React生态"]
status: implemented
created: 2026-08-04
---

# 视频编辑引擎 Elah

> `@elah/editor` 是一个浏览器端的视频编辑 SDK，提供多轨时间轴、WebGL2 预览、媒体管理等能力。VibeCut 用它来在浏览器里做一个轻量级剪辑台。

## 是什么

Elah 是一个 **NLE（Non-Linear Editor，非线性编辑器）** SDK —— 相当于一个运行在浏览器里的 Premiere 引擎。它不是给用户用的桌面软件，而是给开发者用的 JS 库，让你在自己的 Web 应用中嵌入视频编辑功能。

Elah 提供三个核心能力：

```
@elah/editor
  ├── EditorProvider    ← React Context，管理编辑器状态
  ├── Preview           ← WebGL2 视频预览窗口
  ├── Timeline          ← 多轨时间轴 UI
  ├── createDefaultDemuxerFactory  ← 视频文件解码器工厂
  └── Hooks:
        useTimelineEngine()    ← 时间轴引擎
        useTracksStore()       ← 轨道状态 (Zustand)
        usePlaybackStore()     ← 播放状态 (Zustand)
        useMediaLibraryStore() ← 媒体文件管理 (Zustand)
```

一句话总结：**Elah 让你在浏览器里加载视频文件、拖到时间轴上、加特效、预览、导出，就像在用一个精简版的专业剪辑软件。**

## 为什么要在浏览器里做视频编辑

几个不合直觉但实际上很好的理由：

1. **本地视频文件不需要上传**。浏览器可以直接读本地文件（`URL.createObjectURL(file)`），不用先上传到服务器再下载回来。

2. **用户不需要装任何软件**。分享链接就能协作。

3. **代理视频方案**。1080p 原片太大，VibeCut 用 ffmpeg 预生成 540p 代理视频（`generate_proxies.py`，CRF=28, preset=fast），浏览器加载 540p 用于快速编辑，导出时用原始 1080p。代理视频约为原视频的 1/10 大小，但视觉上足够判断镜头好坏。

4. **WebGL2 硬解加速**。现代浏览器的 WebGL2 可以直接在 GPU 上解码视频和渲染特效，流畅度接近原生软件。

## 关键概念

### 1. Project 和 Track

Elah 的数据模型：

```
Project (项目)
  └── Track 1 (轨道 1: 视频)
  │     ├── Clip A (ep1, 10s-15s, 主视频)
  │     └── Clip B (ep3, 45s-50s, 主视频)
  ├── Track 2 (轨道 2: 视频)
  │     ├── Clip C (ep5, 30s-33s, 辅助镜头)
  │     └── Clip D (ep7, 22s-25s, 辅助镜头)
  └── Track 3 (轨道 3: 音频)
        └── Clip E (音轨)
```

每个 Clip 有精确的时间引用：`sourceStartSec` 和 `sourceEndSec`，指向代理视频文件中的具体位置。Elah 基于帧（而非秒）作为基本单位。VibeCut 使用 25 FPS，所以 `secondsToFrames(t)` = `t * 25`。

### 2. Drama 4轨 vs Interview 2轨

`timelineBuilder.js` 的 `buildProjectFromProxyPicks` 支持两种轨道模式：

```javascript
// drama (电视剧): 4 轨
Track 1: main video    ← 主要视频片段
Track 2: supp video    ← 辅助视频片段（B-roll）
Track 3: main audio    ← 主视频的音频
Track 4: supp audio    ← 辅助的音频

// interview (口播): 2 轨
Track 1: main video    ← KEEP sub_clips 构成的视频轨
Track 2: main audio    ← 对应音频
```

电视剧需要 4 轨（因为有主视频和辅助镜头，视频和音频分离），口播只需要 2 轨（单人口播，直接连起来即可）。

轨道数量的检测是自动的：`VibeEdit.jsx` 在加载缓存时比对轨道数，不匹配就触发重建。

### 3. 代理视频 (Proxy) 方案

```
原始视频                              代理视频
1080p, ~400MB/集                      540p, ~40MB/集
完整画质                               轻量预览
                                     ↓
                              generate_proxies.py
                              CRF=28, preset=fast
                              GOP=50（2秒关键帧）
                              Audio=64k mono
                              → proxies/*_540p.mp4
                              → .proxies_manifest.json
```

`proxyEngine.js` 负责解析代理视频路径：

```javascript
// 从 manifest 查找 proxy 文件名
function proxyFileForEp(ep, manifest) {
  const p = manifest.proxies.find(x => x.ep === ep)
  return p?.file || null
}

// 构建 proxy 的完整 URL
export function proxyUrlForEpisode(ep, manifest) {
  return `/proxies/${proxyFileForEp(ep, manifest)}`
}
```

工作流：用户操作 540p 代理视频（流畅）→ 导出时 `export_capcut.py` 引用原始 1080p 路径 → 剪映输出最终成片。

### 4. 口播自动建轨

VibeCut 的口播自动建轨逻辑（`timelineBuilder.js`）：

```javascript
if (segments have sub_clips) {
  // 精切模式：只铺 KEEP 的 sub_clips
  for each segment:
    for each sub_clip where decision === "KEEP":
      create Clip(sourceStart, sourceEnd)
      place on Track 1 sequentially
} else {
  // 粗段模式：铺整个 segment
  for each segment:
    create Clip(source_start, source_end)
    place on Track 1 sequentially
}
```

用户从策划台切到剪辑台，时间轴自动铺好 —— 不需要手动拖拽。

### 5. Demuxer — 视频解复用器

`createDefaultDemuxerFactory()` 是 Elah 的视频文件解码器。它让浏览器能高效地从 MP4 文件中随机提取指定帧，而不需要加载整个文件。对于代理视频剪辑（需要在 30 分钟视频中精确提取第 12'34" 的帧），这个随机访问能力至关重要。

## 在 VibeCut 中的应用

| 文件 | 作用 |
|------|------|
| `vibecut-web/src/pages/VibeEdit.jsx` | 剪辑台主页面，Elah EditorProvider 的宿主 |
| `vibecut-web/src/lib/timelineBuilder.js` | `buildProjectFromProxyPicks()` — 从 picks 构建 Elah Project |
| `vibecut-web/src/lib/proxyEngine.js` | `fetchProxyManifest()` + `proxyUrlForEpisode()` — 代理视频路径解析 |
| `vibecut-web/src/components/ScriptPanel.jsx` | 精切预览面板（绿 KEEP / 红 CUT） |
| `vibecut-web/src/components/TimelineControls.jsx` | 播放控制栏 |
| `vibecut-web/src/components/SourceInspector.jsx` | PR 风格源检视器 |
| `vibecut-server/generate_proxies.py` | 代理视频生成（540p, CRF=28, GOP=50） |

## 动手实验

1. **安装 Elah 并运行最小示例**

```bash
npm install @elah/editor
```

```jsx
import { EditorProvider, Preview, Timeline } from '@elah/editor'
import '@elah/editor/styles.css'

function App() {
  return (
    <EditorProvider stage={{ width: 1920, height: 1080 }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <Preview style={{ flex: 1 }} />
        <Timeline style={{ height: 200 }} />
      </div>
    </EditorProvider>
  )
}
```

2. **理解代理视频概念**

找一段 1080p 视频，用 ffmpeg 转 540p：
```bash
ffmpeg -i input_1080p.mp4 -vf scale=960:540 \
  -c:v libx264 -crf 28 -preset fast -g 50 \
  -c:a aac -b:a 64k -ac 1 output_540p.mp4
```

对比两个文件的大小差异（通常 540p 是 1080p 的 1/10 到 1/5）。

## 前置知识

- [[React与Vite]] — Elah 使用 React 组件和 hooks
- [[JavaScript与React生态]] — npm 包管理、ES Module

## 延伸

- [[Shell与ffmpeg工具链]] — 代理视频生成用 ffmpeg
- [[HTTP服务与SSE流式]] — 代理视频通过 HTTP 服务提供
