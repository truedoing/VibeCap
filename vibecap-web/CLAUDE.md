---
name: vibecap-web
description: VIBECAP React 前端 — 数据台 + 策划台 + 沉浸剪辑台 v0.11
---

## VibeCut Web v0.11

### 架构
```
vibecap-web/
├── src/
│   ├── pages/
│   │   ├── PlanningDesk.jsx    ← 策划台: 主题+AI生成脚本 (SSE流式)
│   │   ├── VibeEdit.jsx        ← 沉浸剪辑台: 源检视器+时间轴
│   │   ├── DataDesk.jsx        ← 数据台: 流水线管理
│   │   ├── Home.jsx            ← 任务台
│   │   └── Series.jsx          ← 剧集页
│   ├── components/
│   │   ├── SourceInspector.jsx ← PR风格源检视器 (纯video+DOM)
│   │   ├── ScriptPanel.jsx     ← 脚本段落面板
│   │   ├── ChatPanel.jsx       ← AI搜索面板
│   │   ├── StoryboardPanel.jsx ← 分镜推荐
│   │   ├── TimelineControls.jsx← 播放控制栏
│   │   └── SearchPanel.jsx     ← 搜索面板封装
│   ├── lib/
│   │   ├── timelineBuilder.js  ← Elah项目构建 (v0.11: manifest驱动, 2/4轨可配)
│   │   └── proxyEngine.js      ← 代理视频解析
│   ├── context/ProjectContext.jsx ← 任务状态管理 (picks/timeline持久化)
│   ├── model/project.js        ← 数据模型 + 剪映导出
│   └── styles/                 ← 主题+混入
├── vite.config.js              ← 代理 → localhost:8765
└── package.json
```

### 启动
```bash
cd /Users/zgl/VIBECAP/vibecap-web
npm run dev
# http://localhost:3000
```

### 路由
- `/` — 任务台
- `/:project/:task/planning` — 策划台 (AI生成脚本)
- `/:project/:task/vibe` — 沉浸剪辑台
- `/data` — 数据台

### 策划台 (PlanningDesk)

两条生成策略:
- **v3 搜索流水线**: 策划→BGE搜索→压缩→审核 (SSE: `/script/generate_script_stream`)
- **v4 故事优先**: LLM通读→分组段落 (SSE: `/script/generate_story_first`)

输出: segments (含source_start/end/section_role) → 保存到SQLite + 文件

### 剪辑台 (VibeEdit)

- **段直达** (v0.11): segment有source_start → 跳过AI搜索, 直接seek源检视器
- **源检视器**: PR风格, I/O标记, 缩放滚动条, 热键
- **时间轴**: interview 2轨 / drama 4轨, 自动切换
- **Proxy**: manifest驱动, 无硬编码文件名
- **持久化**: picks→localStorage + SQLite同步

### 后端依赖
先启动 vibecap-server (8765)，再启动前端。vite.config.js 代理 `/search` `/segments.json` `/script/*` `/proxies/*` → 8765。
