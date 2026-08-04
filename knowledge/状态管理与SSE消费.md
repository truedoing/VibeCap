---
title: 状态管理与SSE消费
type: topic
tags: [framework, technique, implemented]
difficulty: 中等
prerequisites: ["React与Vite", "HTTP服务与SSE流式"]
status: implemented
created: 2026-08-04
---

# 状态管理与 SSE 消费

> 前端怎么记住数据、怎么接收 AI 的实时输出

## 三层状态管理

VibeCut 前端用了三种状态方案，各管不同范围：

| 方案 | 范围 | 用途 |
|------|------|------|
| **React Context** | 任务级 | picks, timeline, segments |
| **Zustand** (Elah内部) | 编辑器级 | playback, tracks, mediaLibrary |
| **useState** | 组件级 | 面板宽度、输入框、加载状态 |

### 为什么不用 Redux

VibeCut 的状态不复杂——一个任务的数据量很小（几十条 segment + picks）。React Context + useState 完全够用。过度引入状态管理库只会增加学习成本。

### ProjectContext

全局任务上下文：`project`, `addPick`, `removePick`, `saveTimelineCache`。通过 `useProject()` hook 访问。

### Zustand (Elah 内部)

Elah 编辑器内部使用 Zustand 管理播放状态、轨道状态、素材库。VibeCut 组件可以直接订阅这些 store（如 `usePlaybackStore(s => s.currentFrame)`）。

## SSE 消费

前端接收 AI 流式输出的方式：

```javascript
const resp = await fetch('/script/generate_script_stream', { method: 'POST', body: ... })
const reader = resp.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  // 解析 SSE 格式: "event: step\ndata: {...}\n\n"
  for (const line of decoder.decode(value).split('\n')) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6))
      // 更新 UI 进度
    }
  }
}
```

## 持久化

- **localStorage:** 项目缓存、任务列表、timeline 缓存
- **服务端同步:** picks 通过 `POST /picks` 同步到 SQLite (debounced 300ms)

## 在 VibeCut 中的应用

| 模式 | 位置 |
|------|------|
| React Context | `ProjectContext.jsx` |
| Zustand stores | VibeEdit.jsx 中的 `usePlaybackStore` |
| SSE 消费 | PlanningDesk.jsx 中的脚本生成流式 |
| localStorage | `model/project.js`, `model/series.js` |

## 前置知识

- [[React与Vite]] — 组件化 + Hooks
- [[HTTP服务与SSE流式]] — SSE 协议原理
