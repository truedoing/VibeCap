---
name: vibecap-server
description: VIBECAP Python 后端 — 视频索引、语义搜索、素材服务
---

## VIBECAP Server — 后端工程

### 架构
```
vibecap-server/
├── server.py              ← 主服务 (8766)
├── analyze_episodes.py    ← 单集分析: 场景切分→ASR→VLM
├── cross_calibrate.py     ← ASR↔VLM 交叉校准
├── clean_data.py          ← 数据清洗 + VLM场景智能合并
├── build_index.py         ← BGE 语义索引重建
├── generate_proxies.py    ← 540p 代理视频生成
├── db.py                  ← SQLite 数据台 (质量评分/剧集管理)
├── match_split.py         ← 解说词↔ASR对齐 → 切分音频
├── parse_docx.py          ← docx → segments.json
├── start.sh               ← 一键启动 (生产模式)
└── requirements.txt
```

### 启动
```bash
cd /Users/zgl/VIBECAP/vibecap-server
./start.sh 都挺好 Task7029

# 或直接
python3 server.py --drama 都挺好 --task Task7029 --port 8766
```

### 依赖
- Python 3.12 (anaconda: `/opt/anaconda3/bin/python3`)
- faster-whisper (本地 ASR，medium 模型推荐)
- sentence-transformers + numpy (BGE 索引)
- zhconv (繁→简归一化)
- MiMo API (`MIMO_API_KEY`) — VLM 画面分析
- DeepSeek API (`DEEPSEEK_API_KEY`) — 分镜推荐
- ffmpeg — 视频处理

## Data Pipeline

### 流水线总览
```
540p代理视频 → 场景切分(10s) → ASR转写 → VLM画面分析 → 交叉校准 → 数据清洗 → 语义索引
                                                                           └→ 质量评分
```

### Step 0: 代理视频生成
```bash
python3 generate_proxies.py --all          # 全46集
python3 generate_proxies.py --ep 1,3,5     # 指定集
```
- 1080p → 540p (960×540, fps=25, ~160MB/集)
- 加速后续帧提取 ~3x

### Step 1: 单集分析
```bash
python3 analyze_episodes.py --ep 6                      # 全流程
python3 analyze_episodes.py --ep 6 --skip-asr           # 仅VLM (ASR已就绪)
python3 analyze_episodes.py --ep 6 --asr-model medium   # medium模型
python3 analyze_episodes.py --ep 6 --vlm-workers 20     # 20并发
```
- **场景切分**: 固定10s间隔，~260-266场景/集
- **ASR**: faster-whisper (medium推荐), VAD过滤, beam_size=5
- **帧提取**: 540p代理视频, fps=1
- **VLM**: MiMo API (mimo-v2.5), 每场景3-8帧, 结构化输出(描述+字幕+深层分析+帧标签)
- **并发**: 默认20 workers (API限100 RPM, 20并发约40 RPM)

### Step 2: 交叉校准
```bash
python3 cross_calibrate.py --ep 6
```
- ASR文本 ↔ VLM字幕 时间窗口匹配
- 双向补漏: VLM确认/修正/补充 ASR
- 人物交叉验证

### Step 3: 数据清洗 + VLM场景合并
```bash
python3 clean_data.py --ep 6
```
- **ASR碎片合并**: 相邻短片段→完整句子 (~200段/集)
- **VLM场景智能合并**: 相邻相似场景自动合并
  - 人物重叠度 40% + 关键词Jaccard 40% + 时长均匀性 20%
  - 相似度 > 65% 即合并
  - 合并后减少 15-18% 冗余场景
- **字幕结构化提取**: VLM原生subtitles字段
- **质量标记**: 片头尾/短描述/浅深度

### Step 4: 语义索引重建
```bash
python3 build_index.py
```
- 优先读 vlm_merged.json (合并后), fallback vlm_analysis.json
- VLM描述 + ASR文本 + 字幕 (字幕权重2x)
- BGE-base-zh-v1.5 embedding (768维)
- 输出: semantic_index.pkl → .npy + mmap

### 质量评分
- **ASR**: 内容密度(40%) + 段质量(40%) + 模型检测加分 + 字幕校准
- **段质量**: 平均段长 + 字密度，自适应识别 tiny/small/medium 模型
- **VLM**: 短描述率 + 浅深度率 + 片头尾率
- **字幕**: 字幕覆盖率

### 优化里程碑
| 版本 | 优化 | 效果 |
|---|---|---|
| v0.7 | 加权n-gram + 繁简归一化 | ASR匹配精度 |
| v0.7 | ASR优先搜索策略 | 台词→跳过AI, 原话直搜 |
| v0.7 | 多任务架构 | ?task= 参数, 一个server服务所有任务 |
| v0.8 | 540p代理视频 | 帧提取 3x 加速 |
| v0.8 | VLM并发 4→12→20 | 单集 32min→6.5min (5x) |
| v0.8 | VLM场景智能合并 | 冗余-15%, 索引质量↑ |
| v0.8 | 评分重构(段长+字密度) | medium模型优势可量化 |
| v0.9 | 流水线文档化 | Data Pipeline 标准化 |

### 数据目录
```
都挺好/
├── sources/ep{N}/        ← 原始数据
│   ├── asr_result.json
│   ├── vlm_analysis.json
│   ├── scenes.json
│   └── asr_calibrated.json
├── sources_clean/ep{N}/  ← 清洗后数据
│   ├── asr_result.json
│   ├── vlm_analysis.json
│   └── vlm_merged.json    ← 场景合并结果
├── proxies/               ← 540p代理视频
├── semantic_index.pkl     ← BGE语义索引
├── vibecap.db             ← SQLite数据台
└── tasks/{task}/          ← 任务数据
```
