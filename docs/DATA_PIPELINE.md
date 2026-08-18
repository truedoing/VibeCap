# ⚠️ 已废弃 (DEPRECATED) — VibeCut 数据加工流程 v2

> **本文件已废弃，勿再参照。** 描述的是 v2 旧架构（whisper ASR + `cross_calibrate.py` + `clean_data.py`），
> 其中 `cross_calibrate.py`、`clean_data.py`、`migrate_db.py` 等脚本**已不存在**。
> 当前生效的管线（字幕 → scene_map → VLM 三层推理）请见 **[DATA_PIPELINE_V3.md](./DATA_PIPELINE_V3.md)**。

## 概述（历史存档）

```
原剧视频 (.mp4)
    │
    ├─→ analyze_episodes.py ──→ sources/epN/
    │      场景切分 + ASR(small) + VLM(结构化字幕)
    │      产出: asr_result.json(含置信度) + vlm_analysis.json(含subtitles)
    │
    ├─→ cross_calibrate.py ──→ sources/epN/
    │      ASR↔VLM 交叉校准：时间窗匹配 + 双向补漏 + 人物验证
    │      产出: asr_calibrated.json + calibration_report.json
    │
    ├─→ clean_data.py ──→ sources_clean/epN/
    │      ASR碎片合并 + VLM结构化字幕(直取) + 质量标记
    │
    └─→ build_index.py ──→ semantic_index.pkl
           BGE 语义索引 (自动发现集数)
```

---

## Step 1: 剧集分析 (`analyze_episodes.py`)

### 用法
```bash
python3 analyze_episodes.py --ep 3 --segment 6 --asr-model small
```

### 参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `--ep` | 1,2,3 | 集数，逗号分隔 |
| `--segment` | 10 | 场景切分间隔(秒)。6=高精度(~440场景/集), 10=标准(~256场景) |
| `--asr-model` | small | faster-whisper 模型: tiny/small/medium |

### Step 1.1: 场景切分
```
算法: 固定时长分段
输出: scenes.json — [{start, end}, ...]
6s间隔: ~440 场景/集
10s间隔: ~256 场景/集
```

### Step 1.2: ASR 转写 (v2)
```
引擎: faster-whisper small (默认, 2.4G)
       tiny → small: 中文识别准确率大幅提升
设备: CPU int8
采样: 16kHz 单声道
VAD: 启用 (min_silence_duration_ms=500)
输出: asr_result.json — [{start, end, text, confidence, words}, ...]

confidence: 对数概率 (avg_logprob)
  > -1.0  = 高置信度
  -1.0~-1.5 = 中等
  < -1.5 = 低置信度 (cross_calibrate 重点修正)
words: 词级时间戳 [{word, start, end, confidence}]

碎片率预期: small~15-20% vs tiny~40-53%
```

### Step 1.3: VLM 画面分析 (v2)
```
引擎: MiMo API (mimo-v2.5)
频率: 每场景 3-8 帧 (按场景时长动态调整)
并发: 4 workers
max_tokens: 2000
输出: vlm_analysis.json — [{scene_id, start, end, description, subtitles, depth_analysis, frame_facts}, ...]

v2 Prompt 结构:
  【描述】画面人物(真名)、动作、场景、构图、光线
  【字幕】识别画面中硬字幕，逐条列出原文。无则写"无"
  【深层分析】角色情绪/人物关系/场景变化/关键视角/台词潜台词
  【帧标签】每帧: 秒数s | 人物名, 动作, 表情, 构图, 场景

subtitles: 结构化字幕数组 — 直接可用，无需正则提取
frame_facts: 每帧的人物标签 — 用于人物交叉验证
```

---

## Step 2: 交叉校准 (`cross_calibrate.py`) ⭐新增

### 目的
ASR(语音转写) 和 VLM(画面字幕识别) 是两套独立的感知系统。交叉校准将它们的时间轴对齐，互相校验补漏，大幅提升台词数据质量。

### 用法
```bash
python3 cross_calibrate.py --ep 3
```

### 算法流程

```
输入: asr_result.json + vlm_analysis.json

Step A: VLM 字幕 → ASR 匹配
  对每个 VLM 场景 [start, end]:
    取时间窗口 [start-3s, end+3s] 内的 ASR 段
    对每条字幕 sub:
      计算 sub 与窗口中每条 ASR text 的文本相似度 (SequenceMatcher)
      最佳匹配 ≥ 0.55:
        高匹配(≥0.9): 提升 ASR 置信度
        中等匹配(0.55-0.9): 用 VLM 字幕修正 ASR 文本 (字幕通常更准确)
      无匹配:
        补充新 ASR 段: {text: sub, source: "vlm_subtitle", confidence: -0.1}

Step B: 低置信度标记
  遍历校准后 ASR，confidence < -1.5 → 标记 _low_confidence

Step C: 人物交叉验证
  对每个 VLM 场景:
    提取 frame_facts 中的人物名 → vlm_chars
    提取 ASR 文本中的人物称呼 → asr_mentions
    交叉比对: ASR称呼 ↔ VLM画面人物

输出:
  asr_calibrated.json: 校准后的 ASR (含 _calibrated, _vlm_sub, _source 标记)
  calibration_report.json: 统计报告
```

### 校准报告示例
```json
{
  "ep": 3,
  "asr_total": 900,
  "confirmed": 85,       // ASR+VLM 双确认
  "asr_corrected": 12,   // ASR 被 VLM 字幕修正
  "vlm_only": 8,         // VLM 发现但 ASR 遗漏的字幕
  "asr_low_conf": 45,    // 低置信度 ASR 段
  "patches": [...]       // 详细修补记录
}
```

---

## Step 3: 数据清洗 (`clean_data.py`)

### v2 改进
- **ASR 源**: 优先读 `asr_calibrated.json`（校准版），fallback `asr_result.json`
- **字幕源**: 直接使用 VLM 的 `subtitles` 结构化字段，正则 fallback 仅用于兼容旧数据
- **校准标记**: 清洗后的 ASR 保留 `calibrated` 标记，建索引时提升权重

### 清洗操作

**ASR 碎片合并** (同 v1):
```
1. 过滤纯噪声词: "啊","嗯","哦","哎","呃","喂"
2. 相邻片段合并: 间隔 < 3s 且缓冲区 < 30 字 → 拼接
3. 过滤结果 < 3 字
效果: EP1 900→188段(-79%), 字量保留 99.5%
```

**VLM 质量标记** (同 v1):
| 标记 | 条件 | 处理 |
|---|---|---|
| `skip_opening` | 描述含"片头/片尾/水墨/演职人员/字幕滚动" | 建索引排除 |
| `short_desc` | 描述 < 20 字 | 降权 |
| `shallow_depth` | 深度分析 < 30 字 | 降权 |

### 用法
```bash
python3 clean_data.py              # 清洗全部
python3 clean_data.py --ep 3       # 指定集数
```

---

## Step 4: 语义索引 (`build_index.py`)

### v2 改进
- **自动发现**: 扫描 `sources_clean/` 下所有集数，不再硬编码
- **权重调整**:
  | type | 来源 | 权重 | 说明 |
  |---|---|---|---|
  | `vlm` | VLM description | 1x | 画面语义搜索 |
  | `asr` | ASR text (校准后) | 1.5x | 校准后的 ASR 权重提升 |
  | `sub` | VLM 结构化字幕 | 2x | 硬字幕精确匹配 |

### 编码
```
模型: BAAI/bge-base-zh-v1.5 (768维)
归一化: L2 normalize
设备: CPU
批次: 32
```

### 用法
```bash
python3 build_index.py
```

---

## Step 5: 数据库导入 (`migrate_db.py`)

```bash
python3 migrate_db.py --force      # 重建数据库
python3 migrate_db.py --dry-run    # 预览
```

---

## 完整流水线命令

```bash
# 单集完整加工
EP=3
rm -rf 都挺好/sources/ep$EP 都挺好/sources_clean/ep$EP
python3 analyze_episodes.py --ep $EP --segment 6 --asr-model small
python3 cross_calibrate.py --ep $EP
python3 clean_data.py --ep $EP
python3 build_index.py
python3 migrate_db.py --force

# 多集批量
python3 analyze_episodes.py --ep 5,6,7 --segment 6 --asr-model small
python3 cross_calibrate.py --ep 5,6,7
python3 clean_data.py --ep 5,6,7
python3 build_index.py
python3 migrate_db.py --force
```

---

## 搜索方式 (server.py)

| 方式 | 匹配类型 | 适用场景 |
|---|---|---|
| 语义搜索 (semantic) | BGE 余弦相似度 | 解说词→画面匹配 |
| 关键词搜索 (keyword) | n-gram 词频 | 台词→对白匹配 |
| 混合搜索 (hybrid) | 语义70% + 关键词30% | 通用 |
| ASR优先 (asr_first) | 纯 ASR + 字幕关键词 | 台词精准匹配 |
| 深度搜索 (deep) | Query扩展 + 混合 + LLM重排 | 精搜 |

---

## 文件路径约定

```
VibeCut/
├── {电视剧}/
│   ├── sources/epN/              ← 原始分析产出
│   │   ├── scenes.json
│   │   ├── asr_result.json       ← whisper ASR (v2含置信度)
│   │   ├── vlm_analysis.json     ← VLM分析 (v2含subtitles)
│   │   ├── asr_calibrated.json   ← cross_calibrate 产出 ⭐
│   │   └── calibration_report.json ⭐
│   │
│   ├── sources_clean/epN/        ← 清洗后数据
│   │   ├── asr_result.json       ← 合并碎片(含校准标记)
│   │   └── vlm_analysis.json     ← 结构化字幕+质量标记
│   │
│   ├── semantic_index.pkl        ← BGE 索引
│   ├── character_portraits/      ← 角色人脸
│   ├── characters.json
│   └── tasks/{任务}/             ← 剪辑任务
│
├── vibecut-server/
│   ├── analyze_episodes.py       ← Step 1: 场景+ASR+VLM
│   ├── cross_calibrate.py        ← Step 2: ASR↔VLM校准 ⭐
│   ├── clean_data.py             ← Step 3: 清洗+字幕提取
│   ├── build_index.py            ← Step 4: BGE索引
│   ├── migrate_db.py             ← Step 5: SQLite导入
│   └── server.py                 ← 搜索服务 (+ 加工API)
│
└── vibecut-web/                  ← 前端 (React + Vite)
```

## 质量评分体系

| 维度 | 权重 | 检测逻辑 |
|---|---|---|
| ASR 质量 | 35% | 碎片率 + 内容密度 + 固定间隔检测 |
| VLM 质量 | 40% | 描述完整度 + 深度分析覆盖 |
| 字幕提取 | 10% | 结构化字幕覆盖率 |
| 索引覆盖 | 15% | 是否纳入语义索引 |

---

## 口播采访数据管线 (v0.11)

### 概述

```
采访音频 (.wav)
    │
    ├─→ ASR转写 ──→ sources/asr_*.json
    │      faster-whisper 或外部ASR
    │
    ├─→ classify_transcript.py ──→ sources_clean/classified_*.json
    │      LLM 逐句分类: content / meta / guide / filler
    │      标注 importance (1-5)
    │
    ├─→ segment_transcript.py ──→ sources_clean/segmented.json
    │      LLM 采样 + 主题分段 (5-8组观点单元)
    │
    ├─→ clean_interview_data.py ──→ sources_clean/classified_enhanced.json
    │      LLM 批量清洗文本 (去废词/口误) + 说话人识别 (host/guest)
    │      新增字段: cleaned_text, speaker
    │
    └─→ build_interview_index.py ──→ semantic_embeddings.npy + semantic_metas.json
           BGE 语义索引 (guest-only, speaker边界断开, cleaned_text编码)
```

### Step 1: ASR 分类 (`classify_transcript.py`)

**用法**: 已集成到 server.py 数据台 UI

**算法**: LLM 逐句分为四层
- `content`: 实质内容（方法论、数据、案例）
- `guide`: 引导性语句（承上启下、提出问题）
- `meta`: 元评论（"这个值得讲""我举个例子"）
- `filler`: 纯废句（"嗯""对""好"）

**输出**: `classified_*.json` — 原始 ASR 字段 + `layer` + `importance`

### Step 2: 主题分段 (`segment_transcript.py`)

**算法**: 均匀采样 40 句 → LLM 识别 5-8 个观点单元 → 回填到完整 ASR

**输出**: `segmented.json` — `{groups: [{title, summary, start_sec, end_sec, lines}]}`

### Step 3: 数据增强 (`clean_interview_data.py`)

**用法**:
```bash
python3 clean_interview_data.py --project 杨老师教育
# 跳过清洗，只重建索引:
python3 clean_interview_data.py --project 杨老师教育 --skip-clean
```

**算法**:
- **文本清洗**: 批量 25 句 → LLM 修正 ASR 转写错误、删除口语废词、补全残缺句。最小修正原则（不改写为书面语）
- **说话人识别**: LLM 判断 host/guest。host = 提问/引导/接话；guest = 方法论/数据/案例/长篇论述
- filler/meta 层自动标记为 host

**输出**: `classified_enhanced.json` — 新增 `cleaned_text` + `speaker` 字段

**实测 (杨老师教育)**:
```
467条 → 299句 guest / 168句 host / 38句文本修正 / 88s
```

### Step 4: BGE 索引构建 (`build_interview_index.py`)

**用法**:
```bash
python3 build_interview_index.py --project 杨老师教育
```

**算法**:
- 优先使用 `classified_enhanced.json`（guest-only, cleaned_text）
- **speaker 边界断开**: 不同说话人不合并到同一语义单元
- 用 `cleaned_text` 编码 BGE 768维向量
- 保留 `original_text` 字段用于前端展示

**索引质量对比**:

| 指标 | 旧索引 (原始ASR) | 新索引 (enhanced) |
|---|---|---|
| 数据源 | 全部 ASR | guest-only, cleaned |
| 分块策略 | 固定 15s | speaker边界 + 15s |
| 索引单元 | 73 条 | 66 条 |
| 主持人污染 | "对""你讲吧"混入结果 | 零污染 |
| 模型加载 | 194s (HF mirror) | 8s (HF_HUB_OFFLINE=1) |

### Step 5: 质量评分

| 维度 | 权重 | 检测逻辑 |
|---|---|---|
| ASR 完整度 | 30% | content 占比 + 平均段长 |
| 分类质量 | 25% | filler 占比 + guide/content 比例 |
| 说话人分离 | 20% | guest 占比 + host 过滤率 |
| 索引覆盖 | 25% | 语义单元数 + 时间分布均匀度 |
