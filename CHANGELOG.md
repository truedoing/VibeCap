# VibeCut 更新日志

## v1.2.0 — 产品定位正规化：四台流水线 (2026-08-09)

### 定位变更

从"剪辑台"到"导演台"——VibeCut 的核心能力不是剪辑（时间轴操作在剪映完成），而是**创作决策**：写解说词 + 分镜匹配。

**四台流水线**:

```
项目 ──→ 数据台 ──→ 编剧台 ──→ 分镜台 ──→ 剪映
制片      建索引     写解说词    分镜匹配     精剪导出
```

| 旧名 | 新名 | 角色 | 职责 |
|---|---|---|---|
| 任务台 | **项目** | 制片 | 选项目，管进度 |
| 策划台 | **编剧台** | 编剧 | 写解说词，生成脚本 |
| 剪辑台/沉浸剪辑 | **分镜台** | 导演/分镜师 | 解说词 → 镜头匹配 |
| 数据台 | 数据台 | DIT | 建索引，跑管线 |

### 命名原则

每个名称在影视行业都有精确含义：
- **项目** — 指一部片子（不是 "bug 跟踪系统"）
- **编剧台** — 写解说词的地方
- **分镜台** — 每句词配什么画面（"分镜"是影视行业标准术语）
- **数据台** — 无变更

### 变更范围

- **前端**: `main.jsx` 导航栏文案、`Home.jsx`/`Series.jsx`/`PlanningDesk.jsx`/`VibeEdit.jsx` 页面标题、`project.js` 数据流注释
- **后端**: `server.py` 注释（编剧台/分镜台）、`generate_proxies.py` 注释
- **文档**: `CLAUDE.md`（×3）、`README.md`、`docs/`（全部）、`knowledge/`（全部）
- **非影响**: 代码标识符和路由路径保持不变（PlanningDesk, VibeEdit 等）

### 版本标签

```
v1.2.0 ← 当前
v1.1.0
v1.0.0
```

---

## v1.1.0 — 后端架构重构 (2026-08-08)

### 重构

- **引入 FastAPI**: 替换 `http.server` 标准库，开启自动 Swagger 文档 (`/docs`)、Pydantic 输入校验、内置 CORS/文件上传
- **拆分 server.py (2,866 行)**: God Class → `main.py` (805 行) + 13 个模块
  - `handlers/`: 8 个聚焦模块 (search, tasks, script_gen, pipeline, media, dialogue, static)
  - `lib/`: 5 个共享基础设施 (llm, embeddings, sse, env, subprocess_runner)
- **消除重复代码**:
  - LLM 调用: 10 种实现 → `lib/llm.py` 统一封装 (Moonshot + MiMo)
  - SSE 发射器 + 心跳: 3 次逐字重复 → 通用生成器
  - 子进程执行器: 2 套 95% 相同代码 → `lib/subprocess_runner.py` 统一
  - `load_env()`: 4 处逐字重复 → `lib/env.py`
- **script_agents.py 优化**: `_call_llm` 改用 `lib/llm.py`，消除 25 行重复 LLM 调用代码
- **多模块编译 + 12 端点 API 验证通过**: GET /status, /dramas, /tasks, /search, /segments.json, /asr/classified, /proxies/manifest + POST /tasks/status, /chat, /dialogue_match
- **LLM 成本**: DeepSeek v4 Pro, 14,307,420 tokens, ¥1.80

### 架构收益

| 指标 | v1.0 | v1.1 |
|---|---|---|
| 主入口文件 | `server.py` 2,866 行 | `main.py` 805 行 |
| 模块总数 | 24 脚本 (无分层) | 13 新模块 + 24 脚本 |
| 路由方式 | 手动 if/elif 链 (200 行) | FastAPI 装饰器 (每端点一行) |
| LLM 调用实现 | 10 种 | 1 种 (`lib/llm.py`) |
| API 文档 | ❌ | ✅ Swagger (`/docs`) |
| CORS | 每个端点手写 | `CORSMiddleware` 一行 |
| Multipart 上传 | 150 行手写 boundary 解析 | FastAPI `UploadFile` 自动 |

### 新增文件

```
vibecut-server/
├── main.py              ← FastAPI 入口 + 32 路由
├── config.py            ← CLI 参数 + 项目配置 + 路径解析
├── lib/                 ← 共享基础设施 (5 模块, 377 行)
│   ├── llm.py           ← 统一 LLM 调用 (Moonshot/MiMo)
│   ├── embeddings.py    ← BGE 模型单例
│   ├── sse.py           ← SSE 发射器 + 心跳
│   ├── env.py           ← .env 加载
│   └── subprocess_runner.py ← 子进程执行器
└── handlers/            ← 接口处理器 (8 模块, 2,107 行)
    ├── search.py        ← 6 种搜索引擎
    ├── tasks.py         ← 任务 CRUD
    ├── script_gen.py    ← AI 脚本生成 (v3/v4/refine SSE)
    ├── pipeline.py      ← 后台加工流水线
    ├── media.py         ← 媒体服务
    ├── dialogue.py      ← 对话/台词/分镜
    └── static.py        ← SPA 前端回退
```

### 版本标签

```
v1.1.0 ← 当前
v1.0.0 (重构前基线)
```

---

## v1.0.0 — 正式命名 + Agent 架构升级 (2026-08-04)
