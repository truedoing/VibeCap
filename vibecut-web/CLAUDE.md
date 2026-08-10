---
name: vibecut-web
description: VibeCut React 前端 — 编剧台(脚本+精切) + 分镜台(解说词→镜头匹配) v1.2
---

## VibeCut Web v1.2

后端 v1.1 引入 FastAPI，API 文档: http://localhost:8765/docs

### 架构
```
vibecut-web/
├── src/
│   ├── pages/
│   │   ├── PlanningDesk.jsx    ← 编剧台: 脚本生成 + 精切按钮 + 页签切换
│   │   ├── VibeEdit.jsx        ← 分镜台: 解说词→镜头匹配 + 精切预览
│   │   ├── DataDesk.jsx        ← 数据台: 流水线管理
│   │   ├── Home.jsx            ← 项目
│   │   └── Series.jsx          ← 剧集页
│   ├── components/
│   │   ├── SourceInspector.jsx ← PR风格源检视器 (纯video+DOM)
│   │   ├── ScriptPanel.jsx     ← 脚本面板 (粗段/精切自适应)
│   │   ├── ChatPanel.jsx       ← AI搜索面板 (口播/影剧自适应)
│   │   ├── StoryboardPanel.jsx ← 分镜推荐
│   │   ├── TimelineControls.jsx← 播放控制栏
│   │   └── SearchPanel.jsx     ← 搜索面板封装
│   ├── lib/
│   │   ├── timelineBuilder.js  ← Elah项目构建 (interview/drama双模式)
│   │   └── proxyEngine.js      ← 代理视频解析
│   ├── context/ProjectContext.jsx ← 任务状态管理 (picks/timeline持久化)
│   ├── model/project.js        ← 数据模型 + 剪映导出
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
- `/:project/:task/planning` — 编剧台 (脚本+精切)
- `/:project/:task/vibe` — 分镜台

### 编剧台 (PlanningDesk) v1.0

三栏布局: **口播素材** | **解说脚本** | **AI 助手**

- 口播素材: 可向左折叠, 搜索/精炼过滤
- AI 助手: 🧠 AI生成脚本 + ✂️ 精切 并排按钮
- 解说脚本: 粗剪/精切 页签切换
  - 粗剪: 段卡列表 (编辑/排序/删除)
  - 精切: sub_clips 列表 (✅KEEP / ❌CUT, 完整文本)

流程: 输入主题 → AI生成粗段 → 审核 → 精切 → 切精切页签查看 → 导出

### 分镜台 (VibeEdit) v1.0

解说词 → 镜头匹配工作台。搜索策略基于"导演思维"（叙事节拍 + episode_marker + BGE语义 + 人物过滤）。

- **口播自动建轨**: segments有sub_clips → 仅KEEP sub_clips铺时间轴
- **粗段模式**: 无sub_clips → 用source_start/end建轨
- **时间轴**: interview 2轨 / drama 4轨, segments异步到达后自动切换
- **缓存模式检测**: 加载缓存时比对track数, 不匹配则重建
- **段直达**: segment有source_start → 跳过AI搜索, 直接seek源检视器
- **ScriptPanel**: 精切数据直接显示 (绿✅/红❌), 无页签

### 后端依赖
先启动 vibecut-server (8765)，再启动前端。vite.config.js 代理 `/search` `/segments.json` `/script/*` `/proxies/*` → 8765。
