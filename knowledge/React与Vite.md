---
title: React与Vite
type: topic
tags: [framework, language, implemented]
difficulty: 中等
prerequisites: ["JavaScript与React生态", "ES Module"]
status: implemented
created: 2026-08-04
---

# React 与 Vite

> React 负责 UI，Vite 负责构建。前者让界面组件化，后者让开发秒级热更新。

## 是什么

**React** 是一个 JavaScript UI 框架，核心思想是"组件化"——每个 UI 块（按钮、面板、搜索框）是一个独立组件，组件像搭积木一样拼出整个页面。

**Vite** 是一个前端构建工具。它用浏览器原生 ES Module 做开发（不用打包），用 esbuild 做生产构建（极快）。

**Tailwind CSS** 是一个 CSS 框架，核心理念是 "utility-first"——不用写传统的 `.panel-header { font-size: 14px; ... }`，而是直接在 JSX 元素上写类名 `className="text-sm font-semibold bg-gray-800 rounded-lg"`。

VibeCut 的前端技术栈：`React 19 + Vite 8 + Tailwind CSS`。

## 为什么是 React（而不是 Vue / Svelte）

| 维度 | React | Vue | Svelte |
|------|-------|-----|--------|
| 学习曲线 | 中等 | 平缓 | 平缓 |
| 生态丰富度 | 最大（组件库、工具） | 较小 | 最小 |
| 与 Elah 兼容 | ✅ 官方 React SDK | ❌ 需适配 | ❌ 需适配 |
| 函数式编程 | JSX + 函数组件为主 | 模板语法为主 | 模板语法为主 |

选 React 的三个关键原因：

1. **Elah 视频引擎只提供 React SDK**。`@elah/editor` 的 `EditorProvider`、`Preview`、`Timeline` 都是 React 组件，换 Vue / Svelte 意味着要自己重新封装 Elah API。

2. **React 的函数式组件模型**天然适合"UI = f(state)"的思维方式。当 props 或 state 变化时，React 自动重新渲染受影响的部分。

3. **生态最丰富**。Tailwind CSS、react-router 等库都是 React-first 的。

## 为什么是 Vite（而不是 Webpack）

Vite 相比传统 Webpack 的最大区别在于**开发模式**：

```
Webpack 开发:                       Vite 开发:
源代码 → 打包 → bundle.js → 浏览器    源代码 → 浏览器 (ES Module, 按需请求)
         ↑ 每次改动都重新打包                      ↑ 改动哪个文件就替换哪个文件
         慢（5-30秒）                              快（<1秒热更新）
```

Vite 利用了现代浏览器原生支持的 ES Module import。开发时不做打包，每个 `.jsx` 文件作为独立模块被浏览器直接请求。改动一个文件，浏览器只重新请求这一个文件，秒级刷新。

生产构建时，Vite 用 esbuild（Go 编写）和 Rollup 做打包，比 Webpack 快几个数量级。

## 关键概念

### 1. 组件化思维

VibeCut 的页面由嵌套的组件树构成：

```
App.jsx
  ├── Home.jsx          ← 任务台
  ├── PlanningDesk.jsx  ← 策划台
  │     ├── SourcePanel.jsx    ← 左侧：转写素材
  │     ├── ScriptPanel.jsx   ← 中间：编辑脚本
  │     └── ChatPanel.jsx     ← 右侧：AI 助手
  ├── VibeEdit.jsx      ← 剪辑台
  │     ├── ScriptPanel.jsx   ← 左面板：精切信息
  │     ├── EditorProvider    ← Elah 编辑器 (大预览 + 时间轴)
  │     └── ChatPanel.jsx     ← 搜索面板
  └── DataDesk.jsx      ← 数据台
```

每个组件只负责自己的一块 UI。`ChatPanel.jsx` 不知道自己被用在策划台还是剪辑台 —— 它只关心 props。

### 2. Hooks — React 的状态管理

```jsx
// useState: 组件的"记忆"
const [searchQuery, setSearchQuery] = useState('')
// searchQuery → 当前值, setSearchQuery → 更新函数

// useEffect: 当依赖变化时执行
useEffect(() => {
  fetch('/search?q=' + searchQuery).then(...)
}, [searchQuery])  // searchQuery 变化时重新搜索

// useCallback / useMemo: 性能优化，避免不必要的重渲染
const handleScroll = useCallback((e) => {
  // 只在依赖变化时重新创建这个函数
}, [deps])
```

### 3. Vite 后端代理

开发时前端跑在 `localhost:3000`，后端跑在 `localhost:8765`。跨域请求需要通过 Vite 代理：

```javascript
// vite.config.js
export default {
  server: {
    proxy: {
      '/search': 'http://localhost:8765',
      '/segments.json': 'http://localhost:8765',
      '/script': 'http://localhost:8765',
      '/proxies': 'http://localhost:8765',
    }
  }
}
```

前端代码里写 `fetch('/search?q=苏大强')`，Vite 开发服务器自动转发到 `http://localhost:8765/search?q=苏大强`。对前端代码来说，前后端看起来在同一个域名下。

### 4. SSE 消费

VibeCut 前端用 `fetch + ReadableStream` 消费 SSE（而不是 `EventSource`，因为 `EventSource` 不支持 POST）：

```javascript
const response = await fetch('/script/generate_script_stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ topic }),
})

const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  // 按 "\n\n" 分割 SSE 事件
  const events = buffer.split('\n\n')
  buffer = events.pop()  // 最后一个可能不完整
  for (const event of events) {
    // 解析 "event: progress\ndata: {...}" 格式
  }
}
```

## 在 VibeCut 中的应用

**`vibecut-web/src/`** 目录结构：

| 文件 / 目录 | 作用 |
|------------|------|
| `pages/PlanningDesk.jsx` | 策划台主页面（三栏布局） |
| `pages/VibeEdit.jsx` | 剪辑台主页面（Elah 集成） |
| `pages/DataDesk.jsx` | 数据台（流水线管理） |
| `pages/Home.jsx` | 任务台首页 |
| `components/ScriptPanel.jsx` | 共享脚本面板（精切/粗段自适应） |
| `components/ChatPanel.jsx` | 共享 AI 搜索面板 |
| `components/SourceInspector.jsx` | PR 风格源检视器 |
| `lib/timelineBuilder.js` | Elah 项目构建逻辑 |
| `lib/proxyEngine.js` | 代理视频 URL 解析 |
| `context/ProjectContext.jsx` | 全局任务状态管理 |
| `styles/theme.js` + `styles/mixins.js` | 主题和样式混入 |

## 动手实验

1. **用 Vite 创建一个 React 项目**

```bash
npm create vite@latest my-test -- --template react
cd my-test && npm install && npm run dev
```

打开 `localhost:5173`，改动 `src/App.jsx` 的文本，观察浏览器瞬间更新。

2. **配置 Vite 代理**

在 `vite.config.js` 中加入：
```javascript
server: {
  proxy: {
    '/api': 'http://localhost:8765'
  }
}
```

然后在前端 `fetch('/api/search?q=test')`，观察 Network 面板 —— 请求被转发到了 8765 端口。

3. **写一个消费 SSE 的 React 组件**

```jsx
function SSEStreamer() {
  const [messages, setMessages] = useState([])
  const fetchStream = async () => {
    const res = await fetch('/script/generate_script_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: '测试' })
    })
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      setMessages(prev => [...prev, text])
    }
  }
  return <div>
    <button onClick={fetchStream}>开始</button>
    {messages.map((m, i) => <p key={i}>{m}</p>)}
  </div>
}
```

## 前置知识

- [[JavaScript与React生态]] — JSX、ES Module、npm 基础
- [[HTTP服务与SSE流式]] — SSE 的工作原理

## 延伸

- [[视频编辑引擎Elah]] — Elah 的 React 组件如何集成到 VibeEdit
- [[L1-语言与运行时]] — JavaScript 和 npm 基础
