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

> 无障碍 + 无样式 UI 原语 — VibeCut 的界面基础组件

## 是什么

Radix UI 是一套**无样式、无障碍**的 React UI 原语（Primitives）。它提供交互逻辑（键盘导航、焦点管理、ARIA 属性），但不提供视觉样式。

### 为什么不用 MUI/Ant Design

完整的组件库（MUI/Ant Design）自带设计语言。用它们的按钮就是 Material Design 风格。VibeCut 需要自己的视觉风格（暗色主题、自定义颜色），Radix UI 的无样式特性正好匹配。

## VibeCut 中使用的 8 个 Radix 包

| 包 | 用途 |
|----|------|
| `@radix-ui/react-dialog` | 模态对话框（导出确认、设置） |
| `@radix-ui/react-dropdown-menu` | 右键菜单 |
| `@radix-ui/react-popover` | 弹出面板（搜索结果详情） |
| `@radix-ui/react-scroll-area` | 自定义滚动条 |
| `@radix-ui/react-select` | 下拉选择（剧集选择、模式切换） |
| `@radix-ui/react-tabs` | 页签切换（粗剪/精切页签） |
| `@radix-ui/react-tooltip` | 工具提示 |
| `@radix-ui/react-slot` | 插槽组合（shadcn/ui 依赖） |

## shadcn/ui 工具链

VibeCut 遵循 shadcn/ui 模式，使用三个工具库：

- **class-variance-authority (CVA):** 组件变体管理（按钮的 variant + size）
- **clsx:** 条件 className 拼接
- **tailwind-merge:** Tailwind 类名冲突合并

结合到 `cn()` 工具函数：`cn = clsx + tailwind-merge`

## 自建设计系统

在 Radix 之上，VibeCut 构建了自己的设计系统：
- `styles/theme.js` — 颜色、间距、字体 token
- `styles/mixins.js` — 可复用的样式工厂（btn, card, panel）
- `index.css` — Tailwind CSS 变量 + 暗色主题

## 前置知识

- [[React与Vite]] — React 组件化思维

## 学习资源

- Radix UI 官网 (radix-ui.com) — 每个 primitive 的交互演示
- shadcn/ui — CVA + clsx + tailwind-merge 模式
