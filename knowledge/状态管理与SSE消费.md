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

> VibeCut 前端的三层状态体系：React Context（任务状态）+ Zustand（Elah 编辑器状态）+ useState（组件本地状态）。SSE 流式数据通过 fetch + ReadableStream 消费。

## 是什么

**状态管理** = 前端数据存在哪里、怎么改、谁可以读。VibeCut 用了三层：

- **React Context**（`ProjectContext.jsx`）：全局任务数据——picks、segments、timeline 缓存
- **Zustand**（Elah 内部）：编辑器状态——tracks、clips、播放位置、媒体库
- **useState / useRef**：组件本地状态——搜索框输入、UI 开关、临时缓存

**SSE（Server-Sent Events）** = 服务端向客户端推送数据流的协议。VibeCut 用 SSE 接收 AI 生成的实时进度（编剧台、精切引擎）。

## 为什么需要用多层状态

| 层级 | 用什么 | 存什么 | 生命周期 |
|------|--------|--------|---------|
| 全局任务 | React Context | picks、segments 缓存、timeline | 页面级别（路由切换保持） |
| 编辑器 | Zustand (Elah) | tracks、clips、media | 引擎实例（页面刷新重置） |
| 组件本地 | useState/useRef | 搜索框输入、UI 开关 | 组件挂载期间 |

**为什么不能全放 Context？** 如果 Elah 的 tracks/clips 放 Context，每一帧播放都会触发整个 React 树的 re-render——性能灾难。Zustand 的选择性订阅允许 Elah 的 Canvas 只在 tracks 变化时更新，而不受其他状态影响。

**为什么不能全放 useState？** VibeEdit 拆成了一堆子组件（Preview、Timeline、ScriptPanel、ChatPanel），它们需要共享一些数据（比如当前选中的 segment），纯 useState 传递会导致 props drilling 地狱。

## 关键概念

### 1. React Context 模式（ProjectContext.jsx）

```jsx
// 1. 创建 Context
const TaskContext = createContext(null)

// 2. Provider 包裹组件树，注入状态
export function TaskProvider({ children }) {
  const [project, setProject] = useState(EMPTY)
  const { seriesId, taskId } = useParams()

  // 加载任务（URL → internal ID 匹配 → 服务端同步）
  useEffect(() => { /* 加载逻辑 */ }, [seriesId, taskId])

  // picks 操作函数（通过 useCallback 稳定引用）
  const handleAddPick = useCallback((sid, seq, type, clipRef) => {
    setProject(prev => {
      const next = { ...prev, picks: { ...prev.picks } }
      // ... 不可变更新
      persist(next)
      return next
    })
  }, [persist])

  // 组合 value 对象
  const value = { project, seriesId, taskId, addPick, removePick, ... }
  return <TaskContext.Provider value={value}>{children}</TaskContext.Provider>
}

// 3. 消费 Context
export function useProject() {
  const ctx = useContext(TaskContext)
  if (!ctx) throw new Error('useProject must be used within TaskProvider')
  return ctx
}
```

关键设计：

- **内存优先，持久化兜底**：picks 先更新内存 (`setProject`)，然后 200ms 防抖写 localStorage + 300ms 防抖同步后端 SQLite。
- **不可变更新**：每次 `setProject` 都创建新对象 `{ ...prev, picks: { ...prev.picks } }`，React 才能检测到变化并触发重渲染。
- **孤儿数据救助**：如果用户不小心关掉页面，localStorage 中的 `vibecut-task--` 键会保存未关联到具体任务的 picks，下次打开任务时自动合并。

### 2. localStorage 持久化策略

```js
// 200ms 防抖写 localStorage
const persist = useCallback((p) => {
  clearTimeout(saveTimer.current)
  saveTimer.current = setTimeout(() => {
    saveTask(p)  // localStorage.setItem('vibecut-tasks', JSON.stringify(allTasks))
    syncPicksToServer(taskId, p.picks || {})  // 300ms 防抖 POST /picks
  }, 200)
}, [seriesId, taskId])
```

双重持久化：localStorage（即时，离线可用）+ 后端 SQLite（可靠，跨设备）。防抖延迟避免频繁写入：用户连续快速点击 5 次 addPick，只触发一次保存。

### 3. SSE 流式消费

VibeCut 前端消费 SSE 的方式（`PlanningDesk.jsx` 和 `VibeEdit.jsx`）：

```js
// 发起 SSE 请求
const response = await fetch('/script/generate_story_first', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ topic: '学习方法', task: '0801学习新东方' })
})

// 手动解析 ReadableStream
const reader = response.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break

  const chunk = decoder.decode(value, { stream: true })
  // 手动按行分割（SSE 是 "data: {...}\n\n" 格式）
  const lines = chunk.split('\n')
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6))
      // 根据事件类型更新 UI
      switch (event.type) {
        case 'progress': updateProgress(event.step); break
        case 'segment': appendSegment(event.segment); break
        case 'done': markComplete(); break
        case 'error': showError(event.message); break
      }
    }
  }
}
```

为什么不用 EventSource API？EventSource 只支持 GET 请求，而 VibeCut 的 AI 生成需要 POST（传递 topic、task 等参数）。所以用手动 `fetch + ReadableStream` 解析。

### 4. Debounced 服务端同步

```js
// ProjectContext.jsx 第 11-21 行
let _picksSyncTimer = null
function syncPicksToServer(taskId, picks) {
  clearTimeout(_picksSyncTimer)
  _picksSyncTimer = setTimeout(() => {
    fetch('/picks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: taskId, picks }),
    }).catch(() => {})  // 静默失败：网络不可用时不影响本地操作
  }, 300)
}
```

300ms 防抖同步到后端。`catch(() => {})` 是刻意设计的——网络不可用时不同步后端，但本地 localStorage 仍然保存。网络恢复后下次打开任务会自动同步。

## 在 VibeCut 中的应用

**`ProjectContext.jsx`**（217 行）：
- `TaskProvider`：全局任务状态管理（picks、timeline、mediaCache）
- `useProject()` hook：组件获取任务数据的唯一入口
- `EmptyProjectProvider`：给不需要任务的页面（Home、Series）
- `ProjectProvider`：向后兼容的空壳

**`VibeEdit.jsx`** 的 SSE 消费：
- `ProgramLoader` 组件：监听 `engine.on('change')` → 300ms 防抖保存 timeline
- 自动建轨逻辑：`segments` 到达 → 检测模式 → 构建 project → 加载到 engine

**Elah 内部 Zustand stores**：
- `useTimelineEngine`：引擎实例引用
- `useTracksStore`：轨道状态（选择器：只订阅当前组件关心的轨道）
- `usePlaybackStore`：播放状态（currentFrame、isPlaying）
- `useMediaLibraryStore`：媒体库状态（assets、order）

## 前置知识

- [[React与Vite]] — React Context、useState、useEffect 的基础用法
- [[HTTP服务与SSE流式]] — 后端的 SSE 推送实现

## 延伸

- [[视频编辑引擎Elah]] — Elah 内部用 Zustand 做状态管理
- [[SQLite数据层设计]] — 后端 `/picks` 持久化的数据库结构

## 动手实验

1. **观察 Context 的数据流**
在 PlanningDesk 页面打开 React DevTools → Components 标签 → 搜索 `TaskProvider` → 查看 `value` 对象的结构。

2. **模拟一次 SSE 流式消费**
```js
// 打开浏览器 Console
const resp = await fetch('/script/generate_story_first', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ topic: '测试', task: '你的任务名' })
})
const reader = resp.body.getReader()
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  console.log(new TextDecoder().decode(value))
}
```

## 学习资源

- React 官方文档: useContext + useReducer — Context 模式最佳实践
- Zustand 官方文档 — 轻量状态管理的完整指南
- MDN: Server-Sent Events — SSE 协议标准
