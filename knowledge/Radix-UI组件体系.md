---
title: Radix-UI组件体系
type: topic
tags: [framework, language, implemented]
difficulty: 入门
prerequisites: ["React与Vite"]
status: implemented
created: 2026-08-04
---

# Radix UI 组件体系

> Radix UI = "无头"（headless）UI 原语：只提供行为和可访问性，不提供样式。VibeCut 用 8 个 Radix 包构建了所有交互组件。

## 是什么

**Radix UI** 是一套 React 组件库，特色是**无头（headless）**——组件提供完整的行为逻辑（打开/关闭、键盘导航、焦点管理、ARIA 属性），但**不提供任何默认样式**。样式完全由你控制。

```
传统组件库 (MUI / Ant Design):         Radix UI:
┌──────────────────────┐              ┌──────────────────────┐
│ <Button variant="primary">          │ <Dialog.Root>        │
│   点击                    │              │   <Dialog.Trigger>   │
│ </Button>              │              │     打开              │
│                        │              │   </Dialog.Trigger>  │
│ 自带: 蓝色背景、圆角、   │              │   <Dialog.Portal>    │
│ 阴影、hover效果、       │              │     <Dialog.Overlay  │
│ ripple动画...           │              │       className="..."│
│                        │              │     />               │
│ 问题: 要覆盖样式时很痛苦 │              │     <Dialog.Content  │
│  需要 !important 或     │              │       className="..."│
│  深层 CSS 选择器        │              │     >                │
└──────────────────────┘              │       实际内容          │
                                      │     </Dialog.Content> │
                                      │   </Dialog.Portal>    │
                                      │ </Dialog.Root>        │
                                      │                       │
                                      │ 你完全控制每个元素的   │
                                      │ className 和 style     │
                                      └──────────────────────┘
```

## 为什么不用 MUI / Ant Design

| 传统组件库 | Radix UI |
|---|---|
| 自带完整样式 | 零样式，纯行为 |
| 定制样式需要覆盖（hack） | 定制样式就是写 Tailwind class |
| 统一视觉风格（所有 App 长得一样） | 完全自由的视觉设计 |
| 打包体积大（全量引入） | 按需安装（用哪个装哪个） |
| 大版本升级 = 样式大改 | 升级只影响行为，不影响样式 |

VibeCut 是一个**视觉设计自定义程度高**的工具型应用——暗色主题、紧凑布局、自定义配色系统。如果用 MUI，要覆盖它所有的默认样式，成本太高。Radix 提供行为，自己写样式——完全匹配 VibeCut 的需求。

## 关键概念

### 1. Compound Component 模式

Radix 使用复合组件模式——父组件管理状态，子组件各自渲染：

```jsx
// Dialog 组件：Root 管理 open/close 状态
<Dialog.Root>
  <Dialog.Trigger>打开设置</Dialog.Trigger>
  <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 bg-black/50" />
    <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                                bg-gray-900 rounded-lg p-6 shadow-xl">
      <Dialog.Title className="text-lg font-bold">设置</Dialog.Title>
      <Dialog.Description className="text-sm text-gray-400">
        调整你的偏好
      </Dialog.Description>
      {/* 实际内容 */}
      <Dialog.Close className="absolute top-3 right-3">✕</Dialog.Close>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
```

每个子组件渲染一个独立的 DOM 元素，你可以给每个元素加自己的 `className`。Dialog.Root 不渲染任何可见元素——它只提供 React Context 来传递 open/close 状态。

### 2. shadcn/ui 模式

VibeCut 实际使用的是 **shadcn/ui** 模式——基于 Radix 原语 + CVA + clsx + tailwind-merge 的组合：

```jsx
// 用 CVA 定义组件变体
import { cva } from 'class-variance-authority'

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium",
  {
    variants: {
      variant: {
        default: "bg-blue-600 text-white hover:bg-blue-700",
        ghost: "hover:bg-gray-800 text-gray-300",
        danger: "bg-red-600 text-white hover:bg-red-700",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
      },
    },
    defaultVariants: { variant: "default", size: "md" },
  }
)

// 使用
<button className={buttonVariants({ variant: "ghost", size: "sm" })}>
  取消
</button>
```

四个工具的职责：

| 工具 | 作用 |
|------|------|
| `class-variance-authority` (CVA) | 定义组件的变体（variant）和尺寸（size） |
| `clsx` | 条件拼接 class 名（`clsx("base", isActive && "active")`） |
| `tailwind-merge` | 合并冲突的 Tailwind class（后写的覆盖先写的） |
| Radix UI | 提供交互行为（open/close、focus、keyboard） |

### 3. VibeCut 使用的 8 个 Radix 包

来自 `package.json`：

| 包 | 用途 | VibeCut 中哪里用 |
|---|---|---|
| `@radix-ui/react-dialog` | 模态对话框 | 设置面板、确认弹窗 |
| `@radix-ui/react-dropdown-menu` | 下拉菜单 | 搜索面板的操作菜单 |
| `@radix-ui/react-popover` | 弹出层（点击触发） | 素材片段的预览弹出层 |
| `@radix-ui/react-scroll-area` | 自定义滚动条 | 脚本面板、素材列表的滚动区 |
| `@radix-ui/react-select` | 下拉选择 | 项目选择、模式切换 |
| `@radix-ui/react-separator` | 分隔线 | 面板之间的分隔线 |
| `@radix-ui/react-slot` | 插槽（多态组件） | 按钮作为链接时使用 |
| `@radix-ui/react-tabs` | 标签页 | 策划台"粗剪/精切"页签切换 |
| `@radix-ui/react-tooltip` | 工具提示 | 悬停提示（各处的图标说明） |

### 4. 为什么需要 Slot

```jsx
import { Slot } from '@radix-ui/react-slot'

function Button({ asChild, children, ...props }) {
  const Comp = asChild ? Slot : 'button'
  return <Comp {...props}>{children}</Comp>
}

// 用法 1: 渲染为 button
<Button>点击</Button>  // → <button>点击</button>

// 用法 2: 渲染为链接（保留 Button 的样式）
<Button asChild>
  <Link to="/home">首页</Link>  // → <a href="/home" class="button-styles">首页</a>
</Button>
```

`Slot` 允许组件"变成"它的子元素的标签，同时保留子元素的所有 props。这解决了"按钮样式的链接"这个经典需求——不用复制样式代码。

## 在 VibeCut 中的应用

**`Radix-UI` 依赖**（`vibecut-web/package.json` 第 17-25 行）：
- 9 个包，覆盖了所有 UI 交互原语
- 配合 Tailwind CSS 4 提供视觉样式
- 配合 CVA + clsx + tailwind-merge 提供变体系统

**`components.json`**（shadcn/ui 配置文件）：
- 定义组件库的基础配置：样式路径、Tailwind 前缀、CSS 变量映射

## 前置知识

- [[React与Vite]] — React 组件基础和 JSX 语法
- [[L1-语言与运行时]] — JavaScript/Node.js 基础

## 延伸

- [[状态管理与SSE消费]] — Radix 组件状态 vs 全局状态的分工
- [[视频编辑引擎Elah]] — Elah 编辑器也用类似的复合组件模式

## 动手实验

1. **找一个 Radix 组件观察它的 DOM**
打开浏览器 DevTools → Elements 标签 → 打开策划台的一个弹窗 → 观察 Radix Dialog 生成的 DOM 结构（portal、overlay、content 的三层结构）和自动添加的 ARIA 属性（`role="dialog"`、`aria-modal="true"`、`aria-labelledby` 等）。

2. **手写一个 Radix Dialog + Tailwind**
```jsx
import * as Dialog from '@radix-ui/react-dialog'

function MyDialog() {
  return (
    <Dialog.Root>
      <Dialog.Trigger className="px-4 py-2 bg-blue-600 rounded-lg">
        打开
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                                     bg-gray-900 border border-gray-800 rounded-xl p-6 w-96">
          <Dialog.Title className="text-white font-bold text-lg">标题</Dialog.Title>
          <Dialog.Description className="text-gray-400 text-sm mt-2">描述</Dialog.Description>
          <Dialog.Close className="absolute top-3 right-3 text-gray-400 hover:text-white">
            ✕
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
```

## 学习资源

- Radix UI 官方文档 (radix-ui.com) — 每个原语的完整 API
- shadcn/ui 官方文档 (ui.shadcn.com) — CVA + Radix 的最佳实践
- CVA 官方文档 (cva.style) — class-variance-authority 完整用法
