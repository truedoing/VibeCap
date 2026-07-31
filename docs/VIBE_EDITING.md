# Vibe 沉浸式剪辑台 — 技术方案文档

## 概述

Vibe 剪辑台 (`/vibe`) 将"选素材"和"剪辑"合并为单一沉浸式工作台，核心变革是**从"提取片段文件"变为"数据定位引用"** — 编辑阶段不碰 ffmpeg，导出阶段才从 1080p 原剧提取。

## 问题

### 旧架构（两段式）

```
策划台(/planning)                    剪辑台(/timeline)
  ↓                                      ↓
搜索 → /preview_video 提取20s → /copy 永久文件 → addPick → buildProjectFromPicks() → engine.loadProject()
```

**痛点**：
- 片段一旦提取，边界只能在 20s 内调整。扩展边界 → 重新搜索 → 重新提取 → 重新 `/copy`
- 两个页面反复跳转，打断剪辑心流
- 每个 pick 产生碎片文件

### 新架构（代理模式）

```
        搜索面板 ──drag──→ 引擎增量操作
             ↓                  ↓
    picks(时间引用)    engine.addClip() / trimClip() / removeClip()
             ↓                  ↓
     初始 loadProject()     engine.on('change') → 自动保存 → localStorage + SQLite
             ↓
      导出时 ffmpeg 从 1080p 批量提取
```

## 核心设计

### 代理视频系统

生成低分辨率（540p）代理视频用于 Web 端编辑定位，导出时使用原始 1080p 文件。

| 参数 | 值 |
|------|-----|
| 分辨率 | 960×540 (16:9) |
| 编码器 | H.264, preset fast, CRF 28 |
| 关键帧间隔 | 50 帧 (2s @25fps) |
| 音频 | AAC 64k mono |
| Faststart | 是（moov atom 前置，浏览器即时 seek） |
| 单集大小 | ~170MB |
| 存储位置 | `<drama>/proxies/都挺好_XX_540p.mp4` |

### ClipRef 数据模型

```javascript
// 新格式（时间引用）
{ ep: 27, sourceStartSec: 1200.5, sourceEndSec: 1225.0 }

// 旧格式（文件引用，已废弃）
{ ep: 27, start: 1200.5, end: 1225.0, file: "clip_pick_S0_0_ep27.mp4", duration: 24.5 }
```

自动迁移：读取旧 picks → 解析 `file` 字段 → 提取 `sourceStartSec`/`sourceEndSec` → 写回新格式。

### Elah 增量操作

Elah `TimelineEngine` 支持完整的增量 API，无需全量重建：

```javascript
engine.addClip({ type:'video', trackId, src:'/proxies/...', sourceStartFrame, sourceDurationFrames })
engine.removeClip(clipId, trackId)
engine.trimClip(clipId, trackId, startFrame, durationFrames)
engine.batch(() => { /* 原子操作，一个 undo 步 */ })
```

### 拖拽入轨流程

```
搜索面板 → 候选 clip 卡片
  ↓ onDragStart
dataTransfer: { ep, sourceStartSec, sourceEndSec, description, proxyUrl }
  ↓ 拖到 Timeline 轨道区域
onDrop → 解析落点 trackId + startFrame
  ↓
engine.batch(() => {
  engine.addClip({ type:'video', src: proxyUrl, sourceStartFrame, durationFrames })
  engine.addClip({ type:'audio', src: proxyUrl, sourceStartFrame, durationFrames })
  linkClipPair(vClip.id, aClip.id)
})
  ↓
addPick(sid, seq, 'main', { ep, sourceStartSec, sourceEndSec })
  ↓
自动保存 → localStorage + SQLite
```

### 预览系统

点击搜索结果 → 优先使用代理视频直连 seek，无代理时回退 `/preview_video` 提取临时片段：

```
result.ep → proxyUrlForEpisode(ep, manifest)
  ├── 有代理 → vid.src = proxyUrl, vid.currentTime = startTime → 即播
  └── 无代理 → fetch('/preview_video?...') → data.url → vid.src → 等待提取
```

## 布局

```
┌──────────────────────────────────────────────────────────────┐
│  脚本段 (左 260px)  │    预览区 (中, flex:1)    │ AI 搜索 (右 280px) │
│                      │                           │                    │
│  S0 苏大强翻存折 [2主]│   ┌───────────────────┐  │ 搜索框             │
│  S1 明玉冷漠表情 [1主]│   │                   │  │ 结果列表           │
│  S2 兄妹首聚     [0] ←│───│   预览画面        │──│ · EP1 120s ● 35.2 │
│  S3 蒙总办公室   [3主] │   │                   │  │ · EP2 830s ● 33.8 │
│  ...                   │   └───────────────────┘  │                    │
│                        │   源模式 / 时间轴模式    │  [可折叠]          │
│  [可折叠]              │                           │                    │
├────────────────────────┴───────────────────────────┴────────────────────┤
│  源定位器 (~18%)                                                       │
│  EP1 ████████████████████[■候选1■][■■候选2■■]█████████████████████████  │
│  EP2 ████████████████████████████████[■■候选3■■]██████████████████████  │
│  [定入点 I] [定出点 O]  选区: EP1 118s–148s  [↓ 添加到主时间轴]        │
├────────────────────────────────────────────────────────────────────────┤
│  主时间轴 (~35%)                                                        │
│  补镜 ██░░░░████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  主镜 ░░░░████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  音频 ░░░░████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  旁白 ░░░░░░░░░░░░████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
└────────────────────────────────────────────────────────────────────────┘
```

## 双层时间轴设计

### 核心理念

**素材是固定的**（2-3 集 × 40 分钟），AI 快速定位候选区间，用户在源定位器上精调边界，确认后提交到主时间轴。与 Premiere/DaVinci/剪映的"源/节目"双区模型一致。

### 源定位器（Source Locator）

自定义轻量组件（非 Elah），只读 + 标记 + 拖拽：

- **可视化整集**：每集一条横条，时间位置用百分数映射
- **AI 标记**：搜索结果在对应位置打彩色标记，多个标记同时可见
- **播放头拖动**：拖拽播放头 → 预览 `<video>` 实时跟随（scrubbing）
- **入点/出点**：热键 `I` / `O` 设置选区，拖拽边缘调整，点击 AI 标记自动设入出点
- **提交**：选区确认后点击"添加到主时间轴" → `engine.addClip()` 到 Program Timeline

### 主时间轴（Program Timeline）

Elah 4 轨编辑器，只关心已选片段如何排列。与当前实现一致。

### 交互流程

```
AI 搜索 "苏大强翻存折"
  ↓
右侧返回 3 个候选 → 源定位器出现 3 个彩色标记
  ↓
点击标记 → 预览区切换到源模式，seek 到对应位置播放
  ↓
拖拽标记边缘调整入点/出点（或热键 I/O 手动设置）
  ↓
点击 [↓ 添加到主时间轴] → clip 出现在 Program Timeline
  ↓
左侧脚本段计数更新，继续下一段
```

### 预览区模式

- **源模式**：播放源定位器上的内容（搜索预览、scrubbing），出现时自动切换
- **时间轴模式**：播放主时间轴当前位置（点击时间轴播放按钮时切换）

## 文件清单

| 文件 | 用途 |
|------|------|
| `vibecap-server/generate_proxies.py` | 代理视频批量生成脚本 |
| `vibecap-web/src/pages/VibeEdit.jsx` | Vibe 剪辑台主页面 |
| `vibecap-web/src/components/SegmentNav.jsx` | 横向段落导航条 |
| `vibecap-web/src/components/PickPanel.jsx` | 当前段落镜头管理面板 |
| `vibecap-web/src/components/SearchPanel.jsx` | 搜索面板（ChatPanel 包装器 + 拖拽） |
| `vibecap-web/src/components/TimelineControls.jsx` | 共享时间轴控制栏 |
| `vibecap-web/src/hooks/useLinkedClips.js` | 视频/音频 clip 联动 hook |
| `vibecap-web/src/lib/proxyEngine.js` | 代理 URL 解析 + 时间引用转换 |
| `vibecap-web/src/lib/timelineBuilder.js` | 从 proxy picks 构建 Elah Project |
| `vibecap-web/src/model/migrate.js` | 旧 picks 迁移工具 |

## 关键技术决策

### 为什么用 540p 代理？

- 1080p 原片直接加载 → 浏览器解码压力大，seek 延迟 200-500ms
- 540p = 1080p 的 1/4 像素，编码后 ~170MB/集，seek < 50ms
- 即使 DaVinci/Premiere 也有 proxy/offline 工作流 —— 不是 web 的妥协，是视频编辑的通用最佳实践

### 为什么 GOP=50？

- 25fps × 2s = 50 帧一个关键帧
- seek 最大惩罚 = 2s，拖动 clip 边缘时最大重解码距离
- 文件大小影响可忽略（CRF 28 主导压缩）

### Elah EditorProvider 不共享

每个 `EditorProvider` 创建独立的 engine/playback 实例。VibeEdit 独立包裹一个，与 Timeline 页面完全隔离。

### 预览为何需要 useEffect？

React 的 `setState` 是异步的。点击搜索结果 → `setSelectedClip` → 需要等 React commit 渲染 `<video>` 元素 → `useEffect` 在 DOM 就绪后操作 video。使用 `useRef` 暂存待播 clip 信息。

## 导出流程

```
1. 收集 engine.getProject() 所有 clip 的 {ep, sourceStartSec, sourceEndSec}
2. POST /export/extract_clips → 后端按剧集分组，从 1080p 批量 ffmpeg 提取
3. 替换 CapCut draft 的 materials 路径
4. 生成剪映草稿 JSON → 下载
```

## 启动命令

```bash
# 生成代理视频（一次性）
cd vibecap-server
python3 generate_proxies.py --drama 都挺好 --ep 1-5  # 按需
python3 generate_proxies.py --drama 都挺好 --all      # 全部

# 启动后端
python3 server.py --drama 都挺好 --task Task7029 --port 8766

# 启动前端
cd vibecap-web && npm run dev

# 访问
open http://localhost:3000/都挺好/Task7029/vibe
```
