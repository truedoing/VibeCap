---
name: vibecap-web
description: VibeCut React 前端 — 分镜策划台 + 剪辑台
---

## VibeCut Web — 前端工程

### 架构
```
vibecap-web/
├── src/
│   ├── pages/
│   │   ├── VibeEdit.jsx       ← 沉浸剪辑台 (策划+剪辑合并, /vibe)
│   │   ├── DataDesk.jsx       ← 数据台 (/data)
│   │   ├── Home.jsx           ← 任务台 (/)
│   │   └── Series.jsx         ← 剧集页
│   ├── components/
│   │   ├── SourceInspector.jsx ← 源检视器
│   │   ├── ScriptPanel.jsx     ← 脚本面板
│   │   ├── ChatPanel.jsx       ← AI 搜索面板
│   │   └── TimelineControls.jsx← 播放控制栏
│   ├── context/ProjectContext.jsx
│   └── model/project.js       ← 数据模型 + 剪映导出
├── vite.config.js             ← 代理 → localhost:8765
└── package.json
```

### 启动
```bash
cd /Users/zgl/剪辑/vibecap-web
npm install
npm run dev
# http://localhost:3000
```

### 后端依赖
先启动 vibecap-server (8765)，再启动前端。
