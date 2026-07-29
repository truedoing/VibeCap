# VIBECAP — AI 影视解说剪辑台

## 目录

```
VIBECAP/
├── vibecap-server/       ← Python 后端 (端口8765)
├── vibecap-web/          ← React 前端 (Vite, 端口3000)
├── 都挺好/               ← 电视剧数据 (共享 + 任务)
│   ├── 原剧/  sources/   semantic_index.pkl (BGE 768维)
│   ├── rules.json  characters.json  character_portraits/
│   └── tasks/Task7024/   ← 当前任务
│       ├── segments.json (9段解说词)
│       ├── 素材clips/  解说音频.wav  解说文案.docx
│       └── work_dir/tts_segments/ (解说切分)
└── 预设/                 ← 字幕/转场预设 (数据,非工程)
```

## 启动

```bash
# 终端1: 后端
cd vibecap-server && ./start.sh
# 或: /opt/anaconda3/bin/python3 server.py --drama 都挺好 --task Task7024

# 终端2: 前端
cd vibecap-web && npm run dev
```

## 后端 API (server.py)

| 端点 | 说明 |
|---|---|
| GET /search?q=&mode=hybrid|keyword|semantic|deep | 默认 hybird |
| GET /preview_video?ep=&t=&sid= | 返回 {url,file,start,end} |
| POST /assign /copy /storyboard_suggest | 提取/复制/LLM分镜 |
| GET /segments.json /clips/ /tts_segments/ | 静态+媒体 |
| GET /status | 健康检查 |

搜索模式: keyword(ASR词频) / semantic(BGE向量) / hybrid(融合,默认) / deep(+Query扩展+LLM重排)

## 前端页面

- `/` — 分镜策划台 (MatchingDesk): 解说文案 → AI分镜方案 → 搜索匹配画面 → 选取镜头
- `/timeline` — 剪辑台 (Timeline): Elah 4轨编辑器 (原声+解说+补充+旁白)

## 数据流

解说词 → LLM分镜方案 → BGE搜索/关键词 → 选取clip → /copy命名 → Elah时间轴 → 剪映导出

## 依赖

- Python: /opt/anaconda3/bin/python3 (sentence-transformers, numpy)
- MiMo API: MIMO_API_KEY (分镜推荐 + deep搜索重排)
- ffmpeg: 视频处理
- Node: Vite + React 前端
