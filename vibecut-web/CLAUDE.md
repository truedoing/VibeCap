---
name: vibecut-web
description: VibeCut React 前端 — 脚本台(方案全文+编辑+配音) + 分镜台(解说词→镜头匹配) v1.4
---

## VibeCut Web v1.4

后端 v1.1 引入 FastAPI，API 文档: http://localhost:8765/docs

### 架构
```
vibecut-web/
├── src/
│   ├── pages/
│   │   ├── ScriptDesk.jsx      ← 脚本台: 方案全文 + 编辑 + 配音
│   │   ├── VibeEdit.jsx        ← 分镜台: 解说词→镜头匹配
│   │   ├── DataDesk.jsx        ← 数据台: 流水线管理
│   │   ├── Home.jsx            ← 项目
│   │   └── Series.jsx          ← 剧集页
│   ├── components/
│   │   ├── PlanPanel.jsx       ← 方案全文面板 (论点/装置/情绪曲线/图表)
│   │   ├── VoicePanel.jsx      ← 配音面板 (选段生成/试听/克隆音色)
│   │   ├── ScriptPanel.jsx     ← 脚本面板 (粗段/精切自适应)
│   │   ├── SourceInspector.jsx ← PR风格源检视器
│   │   ├── StoryboardSequence.jsx ← 分镜序列
│   │   └── TimelineControls.jsx← 播放控制栏
│   ├── lib/
│   │   ├── timelineBuilder.js  ← Elah项目构建 (interview/drama双模式)
│   │   └── proxyEngine.js      ← 代理视频解析
│   ├── context/ProjectContext.jsx ← 任务状态管理 (picks/timeline持久化)
│   ├── model/series.js         ← 剧集/任务数据
│   └── styles/                 ← 主题+混入
├── vite.config.js              ← 代理 → localhost:8765
└── package.json
```

### 启动
```bash
cd vibecut-web
npm run dev
# http://localhost:3000
```

### 路由
- `/` — 项目
- `/:project/:task/data` — 数据台
- `/:project/:task/script` — 脚本台 (方案全文 + 编辑 + 配音)
- `/:project/:task/vibe` — 分镜台

### 脚本台 (ScriptDesk) v1.4

三栏布局: **方案全文** | **解说脚本** | **配音**

- 方案全文: 论点/装置/核心洞察 + 情绪曲线/解说原声占比/名场面分布/节奏流等图表
- 解说脚本: 段卡列表 (编辑/排序/删除)，支持「📥 导入 JSON」外部导入 + 导出
- 配音: 音色下拉(预设+克隆) + 选中段生成/试听 + 一键全部

### 分镜台 (VibeEdit) v1.0

解说词 → 镜头匹配工作台。搜索策略基于"导演思维"（叙事节拍 + episode_marker + BGE语义 + 人物过滤）。

- **口播自动建轨**: segments有sub_clips → 仅KEEP sub_clips铺时间轴
- **粗段模式**: 无sub_clips → 用source_start/end建轨
- **时间轴**: interview 2轨 / drama 4轨
- **缓存模式检测**: 加载缓存时比对track数, 不匹配则重建
- **段直达**: segment有source_start → 跳过AI搜索, 直接seek源检视器

### 后端依赖
先启动 vibecut-server (8765)，再启动前端。vite.config.js 代理 `/search` `/segments.json` `/script/*` `/proxies/*` `/voiceover` `/tts_segments` → 8765。
