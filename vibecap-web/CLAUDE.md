---
name: vibecap-web
description: VIBECAP React 前端 — 分镜策划台 + 剪辑台
---

## VIBECAP Web — 前端工程

### 架构
```
vibecap-web/
├── src/
│   ├── pages/
│   │   ├── MatchingDesk.jsx   ← 分镜策划台 (/)
│   │   └── Timeline.jsx      ← 剪辑台 (/timeline)
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
