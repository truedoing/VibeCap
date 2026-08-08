# VibeCut — AI 影视解说剪辑台

对原剧进行 VLM 画面分析 + ASR 台词转写，构建 BGE 语义索引，然后根据解说词自动搜索匹配原剧镜头，完成解说短视频的策划与剪辑。

## 工作流

```
解说词 → LLM 分镜 → BGE 搜索匹配画面 → 选取镜头 → 时间轴编排 → 导出
```

## 项目结构

```
VibeCut/
├── vibecut-server/       ← Python 后端 (8765)
│   ├── server.py             主服务 (搜索/预览/分镜/任务管理)
│   ├── analyze_episodes.py   剧集分析 (场景切分/ASR/VLM)
│   ├── build_index.py        构建 BGE 语义索引
│   ├── parse_docx.py         解说文案解析
│   ├── asr_narration.py      解说音频 ASR (faster-whisper)
│   ├── match_split.py        解说词 ↔ ASR 对齐 + 音频切分
│   └── sentence_clip_builder.py  解说 ↔ 原剧匹配引擎
│
├── vibecut-web/          ← React 前端 (Vite, 3000)
│   └── src/pages/
│       ├── Home.jsx           项目选择页
│       ├── MatchingDesk.jsx   分镜策划台
│       └── Timeline.jsx       剪辑台
│
└── {电视剧}/              ← 数据目录 (不提交)
    ├── sources/epN/          VLM + ASR 分析数据
    ├── tasks/                剪辑任务
    ├── character_portraits/  角色人脸
    └── semantic_index.pkl    BGE 语义索引
```

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:truedoing/VibeCut.git
cd VibeCut

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入:
#   MIMO_API_KEY=sk-xxx        (VLM 画面分析)
#   MOONSHOT_API_KEY=sk-xxx  (Moonshot LLM 所有功能)

# 3. 安装依赖
cd vibecut-web && npm install && cd ..
pip install faster-whisper sentence-transformers python-docx numpy

# 4. 准备数据
#   - 原剧视频放入 解说剪辑/都挺好原剧/
#   - 角色肖像放入 {电视剧}/character_portraits/

# 5. 分析剧集
cd vibecut-server
python3 analyze_episodes.py --ep 1,2,3
python3 build_index.py

# 6. 启动
./start.sh 都挺好 Task7029 &    # 后端
cd ../vibecut-web && npm run dev # 前端
# 打开 http://localhost:3000
```

## 技术栈

| 层 | 技术 |
|---|---|
| 画面分析 | MiMo VLM (mimo-v2.5) + background_research 角色注入 |
| 台词转写 | faster-whisper base (本地) |
| 语义搜索 | BGE-base-zh-v1.5 (768维) + 余弦相似度 |
| 分镜生成 | DeepSeek Chat (叙事→视觉查询翻译) |
| 前端 | React 19 + Vite 8 + Tailwind CSS |
| 后端 | Python http.server + ffmpeg |

## API 端点

| 端点 | 说明 |
|---|---|
| GET /search?q=&mode=semantic | BGE 语义搜索 |
| GET /preview_video?ep=&t= | 预览视频片段 |
| POST /storyboard_suggest | LLM 分镜方案 |
| GET /dramas | 电视剧列表 |
| GET /tasks?drama= | 任务列表 |
| POST /tasks/create | 创建任务 |
| GET /segments.json | 当前任务解说数据 |
