# VibeCut — 影视解说素材匹配系统 (React 版)

## 启动
```bash
cd /Users/zgl/剪辑/Task/VibeCut
npm install   # 首次
npm run dev   # → http://localhost:3000
```

## 架构
```
VibeCut/ (React 前端 :3000)
  │
  ├─ Vite proxy → Task7024 Python API (:8765)
  │     ├── /search?q=&mode=
  │     ├── /preview_video?ep=&t=
  │     ├── /assign (POST)
  │     └── /segments.json
  │
  └─ 调用 Python 后端不动

Task7024/ (Python 后端 :8765)
  ├── scripts/clip_search_server.py
  ├── index.html (旧版, 仍可用)
  └── work_dir/ 素材clips/
```

## 目录
```
src/
├── main.jsx          ← 路由: / /timeline /audit
├── pages/
│   ├── MatchingDesk.jsx
│   ├── Timeline.jsx
│   └── Audit.jsx
├── components/       ← 公共组件
└── api/              ← API 封装
```
