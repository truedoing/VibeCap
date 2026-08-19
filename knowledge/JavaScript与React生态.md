---
title: JavaScript与React生态
type: topic
tags: [frontend, concept, implemented]
difficulty: 入门
prerequisites: ["L1-语言与运行时"]
status: implemented
created: 2026-08-19
---

# JavaScript 与 React 生态

> VibeCut 前端的完整技术栈：JS 语言基础 → React 组件化 → Vite 构建

## 是什么

前端开发的三层：

```
JavaScript (语言) → React (UI 框架) → Vite (构建工具)
```

- **JavaScript**：浏览器里唯一能跑的编程语言，负责所有交互逻辑
- **React**：用"组件 + 状态"的方式组织 UI，声明式描述界面
- **Vite**：把 `.jsx`/`.css`/ES Module 编译成浏览器能跑的代码，开发时热更新

VibeCut 的前端就是这三层：`vibecut-web/` 用 React 写页面，Vite 起本地服务器（端口 3000），通过 `vite.config.js` 把 API 请求代理到后端（8765）。

## JavaScript 基础（够用就行）

### 1. 模块化（ES Module）

一个文件一个模块，`export` 导出、`import` 导入：

```js
// lib/math.js
export function add(a, b) { return a + b }

// pages/Home.jsx
import { add } from '../lib/math'
```

**VibeCut 里：** `src/lib/timelineBuilder.js` 导出 `buildProjectFromProxyPicks`，页面 import 后调用。

### 2. 异步：Promise 与 async/await

JS 是单线程，网络请求是异步的。**Promise** 表示"将来会完成的事"，**async/await** 让异步代码像同步一样好读：

```js
// 没有 async/await：回调地狱
fetch('/segments.json').then(r => r.json()).then(d => console.log(d))

// 有 async/await：顺序清晰
async function loadSegments() {
  const r = await fetch('/segments.json')
  const d = await r.json()
  return d
}
```

**关键认知：** `await` 会暂停当前函数，但**不阻塞页面**——其他事件照常处理。这就是 JS 事件循环。

**VibeCut 里：** `VibeEdit.jsx` 加载分镜脚本、配音进度流式解析都用 `await fetch(...)`。

### 3. 事件循环（为什么 UI 不卡）

```
单线程 + 事件队列:
1. 执行同步代码
2. 遇到异步任务 → 挂起，继续执行后面的
3. 事件队列里有结果 → 回调执行
4. 循环
```

所以耗时的网络请求不会卡住界面——`await` 的代码在后台等，界面继续响应。

## React 核心思维

### 1. 组件化

UI 拆成独立组件，每个组件 = 一段 UI + 它的状态：

```jsx
// 一个"段卡片"组件
function SegmentCard({ seg, onSelect }) {
  return (
    <button onClick={() => onSelect(seg.seg_id)}>
      S{seg.seg_id} · {seg.narration_text}
    </button>
  )
}
```

**VibeCut 里：** `src/components/` 下的 `VoicePanel`、`SourceInspector`、`StoryboardOutline` 都是独立组件，页面把它们组合起来。

### 2. Props 与 State（数据从哪来到哪去）

- **Props**：父组件传给子组件的只读数据（像函数的参数）
- **State**：组件自己拥有的可变数据，变了组件就重新渲染

```jsx
function VibeEdit() {
  const [storyboard, setStoryboard] = useState(null)  // state
  return <StoryboardOutline storyboard={storyboard} />  // 作为 props 传下去
}
```

**关键：** 数据单向流动（父→子）。子组件想改父的数据，通过回调函数（`onXxx`）通知父。

**VibeCut 里：** `VibeEdit` 持有 `storyboard`/`selectedShot` 状态，传给 `StoryboardOutline`；大纲点镜头通过 `onSelectShot` 回调通知父组件更新选中。

### 3. Hooks：useState / useEffect / useCallback / useMemo

Hooks 是 React 函数组件的"状态钩子"：

| Hook | 作用 | VibeCut 例子 |
|------|------|-------------|
| `useState` | 声明可变状态 | `const [segments, setSegments] = useState([])` |
| `useEffect` | 副作用（请求/订阅/监听） | 页面加载时 `fetch` 分镜脚本 |
| `useCallback` | 记忆函数引用（避免子组件反复渲染） | `handleReplaceClip` |
| `useMemo` | 记忆计算结果 | `sourceFileToEp` 反查映射 |
| `useRef` | 持有不触发渲染的引用 | `programEngineRef`（时间轴引擎） |

**useEffect 心智模型：** 组件渲染后执行副作用，`[依赖]` 变化时重新执行。

```jsx
useEffect(() => {
  fetch(`/storyboard.json?task=${taskId}`).then(...)
}, [taskId])  // taskId 变了才重新加载
```

### 4. 状态管理：Context + Zustand

- **Context**：跨组件共享状态（避免层层传 props）
- **Zustand**：轻量全局 store（VibeCut 用 Elah 的时间轴 store）

**VibeCut 里：** `src/context/ProjectContext.jsx` 用 Context 共享任务状态（picks/timeline 缓存）；`useSelectionStore`（Zustand）管理时间轴选中。

## Vite 与开发流程

```
cd vibecut-web && npm run dev   # 启动 http://localhost:3000
```

- **HMR（热更新）**：改代码自动刷新，保留页面状态
- **代理**：`vite.config.js` 把 `/search`、`/segments.json` 等转发到后端 8765，前端写相对路径就行
- **生产构建**：`npm run build` 打包成静态文件

## 前端工程的关键习惯

1. **组件拆到能复用为止**：一个页面塞太多逻辑 → 拆组件
2. **数据单向流**：别让子组件偷偷改父状态
3. **Effect 依赖写全**：漏依赖会导致状态不同步（经典 bug）
4. **类型意识**：JS 虽无类型，但函数入参/返回值要想清楚

## 前置知识

- [[L1-语言与运行时]] — JS 也是"语言 + 运行时"，对比理解

## 延伸

- [[React与Vite]] — VibeCut 前端搭建细节
- [[状态管理与SSE消费]] — 前端怎么消费后端流式数据
- [[HTTP服务与SSE流式]] — 后端怎么发 SSE，前端怎么收

## 学习资源

- React 官方教程 (react.dev) — 组件化思维的最佳入门
- Vite 官方文档 — 构建工具配置
- MDN JavaScript — 语言细节查缺补漏
