# 分镜台 (VibeEdit)

## 概述

分镜台 (`/vibe`) 是解说词→镜头匹配的导演工作台。

核心变革：**从"提取片段文件"变为"数据定位引用"** — 编辑阶段不碰 ffmpeg，导出阶段才从 1080p 原剧提取。

## 布局

```
┌──────────┬─────────────────┬──────────────────────┐
│  脚本段   │  预览 (节目引擎)  │  AI 聊天 + 源检视器  │
│  (300px) │                 │  ChatPanel (50%)    │
│          │                 │  ─────────────────  │
│  S0 展开 │  Elah Preview   │  源检视器 (固定高)   │
│  台词 ·  │                 │  · 视频预览          │
│  句0 ·   │                 │  · 时间轴 (3行)      │
│  句1 ·   │                 │  · I/O + 播放控制    │
│  ...     │                 │  · ↓ 插入clip       │
│  ────── │                 │                     │
│  分镜推荐│                 │                     │
│  (170px) │                 │                     │
├──────────┴─────────────────┤                     │
│  节目时间轴                 │  ← 右面板全高        │
│  补镜 | 主镜 | 音频 | 旁白  │                     │
└────────────────────────────┴──────────────────────┘
```

## 组件架构

| 区域 | 组件 | 说明 |
|------|------|------|
| 左侧上 | ScriptPanel | 紧凑标签式段落选择，展开显示句子明细 |
| 左侧下 | StoryboardPanel | AI 分镜推荐列表，点击触发搜索 |
| 中间 | Elah Preview | 节目引擎预览 |
| 底部 | Elah Timeline | 4 轨节目时间轴 |
| 右侧上 | ChatPanel | AI 对话搜索 |
| 右侧下 | SourceInspector | PR 风格源检视器 |

## 源检视器

```
┌──────────────────────┐
│   视频预览 (flex)     │  ← 点击切换 播放/暂停
├──────────────────────┤
│   Row1: 刻度+标记    │  ← 时间刻度 + AI标记 + 选区 + 播放头
│   Row2: 缩放滚动条   │  ← 两端拖拽对称缩放 + 中间拖拽平移
│   Row3: 操作按钮     │  ← { } | ⏸ 🔊 | ↓插入clip | 时间码
└──────────────────────┘
```

- 纯 `<video>` + 自定义 DOM，不依赖 Elah（避免全局 Zustand store 冲突）
- 搜索结果自动设置 I/O 标记
- 播放头自动跟随，超出可视范围时自动平移
- 缩放滚动条 PR 风格：两端拖拽对称缩放，中间拖拽平移
- 热键 I/O + 操作按钮设置入/出点

## 工作流

```
点击解说句子 → AI 生成分镜推荐（左侧 StoryboardPanel）
  ↓
点击分镜推荐 → AI 搜索匹配镜头（右侧 ChatPanel）
  ↓
搜索结果自动加载到源检视器 + 设定 I/O 标记
  ↓
源时间轴 scrub / 调整 I/O 边界
  ↓
点击 ↓插入clip → clip 添加到节目时间轴
```

## 关键技术决策

### 单引擎架构

Elah Zustand store 是模块级单例，无法在一页运行两个引擎。源检视器使用纯 `<video>` + DOM 实现，与节目引擎完全隔离。

### 剧集优先搜索

搜索支持 `eps` 参数 — 代理剧集号自动传给 `/chat` 和 `/search`，优先返回目标剧集结果。

### 缓存隔离

VibeEdit 使用 `vibe_timeline`/`vibe_mediaCache` 独立缓存键，与老分镜台的 `timeline`/`mediaCache` 互不干扰。

### 代理视频

- 540p H.264 编码，~170MB/集
- `faststart` 确保浏览器即时 seek
- GOP=50 (2s @25fps)
- 无代理时自动回退 `/preview_video` 提取

## 文件清单

| 文件 | 用途 |
|------|------|
| `vibecut-server/generate_proxies.py` | 代理视频批量生成脚本 |
| `vibecut-server/server.py` | 后端，新增 `eps` 搜索过滤 |
| `vibecut-web/src/pages/VibeEdit.jsx` | 分镜台主页面 |
| `vibecut-web/src/components/ScriptPanel.jsx` | 脚本段面板（标签式） |
| `vibecut-web/src/components/StoryboardPanel.jsx` | 分镜推荐面板 |
| `vibecut-web/src/components/SourceInspector.jsx` | 源检视器（PR 风格） |
| `vibecut-web/src/components/TimelineControls.jsx` | 共享时间轴控制栏 |
| `vibecut-web/src/components/ChatPanel.jsx` | AI 聊天面板（支持 eps） |
| `vibecut-web/src/hooks/useLinkedClips.js` | 视频/音频联动 hook |
| `vibecut-web/src/lib/proxyEngine.js` | 代理 URL 解析 + 时间引用转换 |
| `vibecut-web/src/lib/timelineBuilder.js` | 从 proxy picks 构建 Elah Project |
| `vibecut-web/src/model/migrate.js` | 旧 picks 迁移工具 |
| `vibecut-web/src/context/ProjectContext.jsx` | 状态管理（双缓存键） |

## 启动命令

```bash
# 生成代理视频
cd vibecut-server
python3 generate_proxies.py --drama 都挺好 --ep 1-5

# 启动后端
python3 server.py --drama 都挺好 --task Task7029 --port 8766

# 启动前端
cd vibecut-web && npm run dev

# 访问
open http://localhost:3000/都挺好/Task7029/vibe
```
