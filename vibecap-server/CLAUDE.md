---
name: vibecap-server
description: VIBECAP Python 后端 — 视频索引、语义搜索、素材服务
---

## VIBECAP Server — 后端工程

### 架构
```
vibecap-server/
├── server.py          ← 主服务 (8765)
├── build_index.py     ← 重建 BGE 语义索引
├── understand.py      ← [待加入] VLM 视频分析
├── match_split.py     ← 解说词↔ASR对齐 → 切分音频
├── asr_narration.py   ← MiMo ASR 转写解说
├── sentence_clip_builder.py ← 匹配引擎
├── parse_docx.py      ← docx → segments.json
├── locate_clips.py    ← 定位高亮台词
├── extract_concat.py  ← 提取+拼接
├── start.sh           ← 一键启动
└── requirements.txt
```

### 启动
```bash
cd /Users/zgl/VIBECAP/vibecap-server
./start.sh 都挺好 Task7024

# 或直接
python3 server.py --drama 都挺好 --task Task7024 --port 8765
```

### 依赖
- Python 3.12 (anaconda: `/opt/anaconda3/bin/python3`)
- sentence-transformers + numpy (BGE 索引)
- MiMo API (`MIMO_API_KEY` 环境变量) — LLM 分镜推荐
- ffmpeg — 视频编辑

### 数据目录
- 电视剧: `/Users/zgl/VIBECAP/<drama>/`
- 任务: `<drama>/tasks/<task>/`
- 索引: `<drama>/semantic_index.pkl`
- 共享: `<drama>/sources/`, `<drama>/原剧/`, `<drama>/rules.json`
