---
title: React与Vite
type: topic
tags: [framework, language, implemented]
difficulty: 中等
prerequisites: ["L1-语言与运行时"]
status: implemented
created: 2026-08-04
---

# React 与 Vite

> VibeCut 前端的技术栈：React 19 组件模型 + Vite 8 构建工具 + Tailwind CSS 4 样式体系。JSX 而非 TypeScript——追求快速迭代。

## 是什么

**React** 是 Meta 开源的 UI 框架，核心理念：UI = f(state)。你定义组件（函数），React 在 state 变化时自动更新 DOM。

**Vite** 是下一代前端构建工具，由 Vue 作者尤雨溪开发。特点：开发服务器秒启动（ESM 按需编译）、HMR 极速热更新、生产构建用 Rollup。

**Tailwind CSS** 是 utility-first 的 CSS 框架：不用写 CSS 文件，直接在 JSX 里用 class 组合样式。

## 为什么选这套组合

| 需求 | 选择 | 理由 |
|------|------|------|
| 组件化 UI | React 19 | 生态最大，function component + hooks 模式成熟 |
| 快速开发 | Vite 8 | HMR 极快，代理配置简单 |
| 样式管理 | Tailwind CSS 4 | 不需要单独维护 CSS 文件，样式随组件走 |
| 类型系统 | JSX (非 TS) | 单人项目，快速迭代优先于类型安全 |

**为什么不用 TypeScript？** VibeCut 是单人开发项目，原型迭代速度第一。TypeScript 的类型体操在快速试错阶段是负担。但如果你在团队中复刻类似项目，建议上 TS。

## 关键概念

### 1. React 19 组件模型

```jsx
// Function Component + Hooks
function PlanningDesk() {
  const { project, addPick } = useProject()  // 自定义 Context hook
  const [searchQuery, setSearchQuery] = useState('')  // 本地状态
  const segments = useRef([])  // 跨渲染持久化（不触发重渲染）

  useEffect(() => {
    // 副作用：数据加载、事件监听
    fetch(`/segments.json?task=${taskId}`)
      .then(r => r.json())
      .then(data => { segments.current = data.segments })
  }, [taskId])  // 依赖变化时重新执行

  return <div>...</div>
}
```

React 19 的关键特性：`useRef` 不触发重渲染（适合缓存大数据）、`useEffect` 带清理函数、自动批处理、`useCallback`/`useMemo` 性能优化。

### 2. Vite 8 构建配置

VibeCut 的 `vite.config.js` 核心是**代理配置**：

```js
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 3000,
    proxy: {
      '/search': 'http://localhost:8765',
      '/script': 'http://localhost:8765',
      '/proxies': 'http://localhost:8765',
      '/segments.json': 'http://localhost:8765',
      // ... 20+ 条代理规则
    }
  }
})
```

前端所有以 `/search`、`/script` 等开头的请求，Vite 开发服务器自动转发到后端 8765 端口。这解决了跨域问题，也让前端代码可以用相对路径发请求。

### 3. Tailwind CSS 4

VibeCut 使用的是 Tailwind v4 + `@tailwindcss/vite` 插件：

```jsx
// 不用写 CSS 文件，class 就是样式
<div className="flex items-center gap-2 px-4 py-2 bg-gray-900 rounded-lg">
  <span className="text-sm text-gray-400">素材</span>
</div>
```

Tailwind 的优势：样式和组件在一起，删除组件时样式也一起消失（不会留下死 CSS）。对于 VibeCut 这种 UI 频繁迭代的项目，这比传统 CSS 文件管理高效得多。

### 4. JSX 语法要点

JSX 是 JavaScript 的语法扩展，看起来像 HTML，但实际上是 `React.createElement()` 的语法糖：

```jsx
// JSX 写法
<div className="panel">{title}</div>

// 等价于
React.createElement('div', { className: 'panel' }, title)
```

关键规则：`className` 而非 `class`（因为 class 是 JS 保留字），`{}` 嵌入 JS 表达式，条件渲染用 `&&` 或三元运算符，列表渲染用 `.map()`。

## 在 VibeCut 中的应用

**页面层（`src/pages/`）**：
- `PlanningDesk.jsx` — 策划台：三栏布局（素材 | 脚本 | AI 助手），粗剪精切页签切换
- `VibeEdit.jsx` — 沉浸剪辑台：Elah 编辑器嵌入，自动建轨，精切预览
- `Home.jsx` — 任务台：项目列表 + 任务管理
- `DataDesk.jsx` — 数据台：流水线管理

**组件层（`src/components/`）**：
- `ScriptPanel.jsx` — 脚本面板（粗段/精切自适应）
- `ChatPanel.jsx` — AI 搜索面板（口播/影剧自适应）
- `SourceInspector.jsx` — PR 风格源检视器

**数据层**：
- `ProjectContext.jsx` — React Context 管理全局任务状态
- `timelineBuilder.js` — 纯逻辑，从 picks 构建 Elah 项目数据
- `proxyEngine.js` — 代理视频 URL 解析

## 前置知识

- [[L1-语言与运行时]] — JavaScript ES6+ 基础（箭头函数、解构、Promise、模块化）
- [[L6-前端工程]] — 前端工程化的全景视角

## 延伸

- [[视频编辑引擎Elah]] — VibeEdit 页面的核心依赖
- [[状态管理与SSE消费]] — ProjectContext + SSE 流式数据处理
- [[Radix-UI组件体系]] — VibeCut 使用的 UI 原语库
- [[HTTP服务与SSE流式]] — 前端的后端依赖

## 动手实验

1. **观察 Vite HMR**
```bash
cd vibecut-web && npm run dev
# 修改 PlanningDesk.jsx 任一行文字，保存后浏览器自动更新（无需刷新）
```

2. **追踪一个请求**
打开浏览器 DevTools Network 标签，在策划台输入搜索词，观察 `/search?q=xxx&mode=semantic` 请求如何从 3000 端口代理到 8765 端口。

## 学习资源

- React 官方文档 (react.dev) — 新版的函数组件 + hooks 教程
- Vite 官方文档 (vite.dev) — 构建配置详解
- Tailwind CSS 文档 (tailwindcss.com) — utility class 速查
