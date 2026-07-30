# VIBECAP 数据加工流程

## 概述

```
原剧视频 (.mp4)
    │
    ├─→ analyze_episodes.py ──→ sources/epN/
    │      场景切分 + ASR + VLM
    │
    ├─→ clean_data.py ──→ sources_clean/epN/
    │      ASR碎片合并 + 字幕提取 + 质量标记
    │
    └─→ build_index.py ──→ semantic_index.pkl
           BGE 语义索引
```

---

## Step 1: 剧集分析 (`analyze_episodes.py`)

### 输入
- 原剧视频 (1080p MP4)
- `background_research.json`（角色描述，自动注入 VLM prompt）

### 处理步骤

#### 1.1 场景切分
```
算法: 固定时长分段
默认间隔: 10s（生产）/ 6s（高精度）
输出: scenes.json — [{start, end}, ...]
平均: ~250-440 场景/集
```

#### 1.2 ASR 转写
```
引擎: faster-whisper tiny (本地 CPU)
模型: Systran/faster-whisper-tiny
采样: 16kHz 单声道
输出: asr_result.json — [{start, end, text}, ...]
平均: ~900 原始段/集（大量碎片）
```

#### 1.3 VLM 画面分析
```
引擎: MiMo API (mimo-v2.5)
频率: 每场景 3-8 帧
并发: 4 workers
输出: vlm_analysis.json — [{scene_id, start, end, description, depth_analysis, frame_facts}, ...]

Prompt 结构:
  已知角色信息 (background_research.json)
  【描述】不超过150字，人物（真名）、动作、场景、构图、光线
  【深层分析】角色情绪、人物关系、场景变化、关键视角、台词潜台词
  【帧标签】每帧标签：人物名、动作、表情、构图、场景
```

### 输出文件
```
sources/epN/
├── scenes.json          场景时间轴
├── asr_result.json       台词转写
├── vlm_analysis.json     画面描述 + 深度分析
├── audio.wav              提取的音频（可选删除）
└── frames/                关键帧图片（可选删除）
```

---

## Step 2: 数据清洗 (`clean_data.py`)

### 2.1 ASR 碎片合并

**问题**: faster-whisper 输出大量短碎片（"嗯"、"啊"、"过去"），EP1-4 中 40-53% 的片段 < 5 字符。

**算法**:
```
输入: asr_result.json (原始碎片)
1. 过滤纯噪声词: "啊","嗯","哦","哎","呃","喂"
2. 相邻片段合并:
   - 间隔 < 3s 且缓冲区 < 30 字 → 拼接
   - 否则 → 输出当前缓冲区，开始新缓冲区
3. 过滤结果 < 3 字
输出: asr_result.json (合并后)

效果: EP1 900→188段 (-79%), 字量保留 99.5%
```

### 2.2 VLM 字幕提取

**问题**: VLM 描述中提到了字幕但混在长文本里，无法直接搜索。

**算法**:
```
输入: vlm_analysis.json
1. 正则匹配字幕模式:
   - "字幕显示/揭示/写着 ..."
   - '字幕"..."'
   - 字幕「...」
   - 字幕：...
2. 从 description 和 depth_analysis 中分别提取
3. 去重
输出: 每条场景新增 subtitles: ["字幕1", "字幕2", ...]

效果: EP1-4 提取 192 条，EP27-29 提取 223 条，共 415 条
```

### 2.3 质量标记

**标记规则**:
| 标记 | 条件 | 处理 |
|---|---|---|
| `skip_opening` | 描述含"片头/片尾/水墨/演职人员/字幕滚动" | 建索引排除 |
| `short_desc` | 描述 < 20 字 | 降权 |
| `shallow_depth` | 深度分析 < 30 字 | 降权 |

### 输出
```
sources_clean/epN/
├── asr_result.json      合并后的 ASR（碎片已消除）
├── vlm_analysis.json    带 subtitles 字段 + tags 标记
```

---

## Step 3: 语义索引 (`build_index.py`)

### 索引条目类型

| type | 来源 | 权重 | 用途 |
|---|---|---|---|
| `vlm` | VLM description | 1x | 画面语义搜索 |
| `asr` | ASR text | 1x | 台词关键词搜索 |
| `sub` | VLM 提取字幕 | **2x** | 硬字幕精确匹配 |

### 编码
```
模型: BAAI/bge-base-zh-v1.5 (768维)
归一化: L2 normalize
设备: CPU (MPS 内存不足时降级)
批次: 32
```

### 搜索方式

| 方式 | 匹配类型 | 适用场景 |
|---|---|---|
| 语义搜索 (semantic) | BGE 余弦相似度 | 解说词→画面匹配 |
| 关键词搜索 (keyword) | n-gram 词频 | 台词→对白匹配 |
| 混合搜索 (hybrid) | 语义70% + 关键词30% | 通用 |

---

## 台词匹配专线 (`/dialogue_match`)

用于高亮台词 ↔ 原剧对白匹配。

### 算法流程

```
高亮台词段落
    ↓
DeepSeek 拆句 + 生成变体
    "爸，你是想跟大哥去美国吧？" → ["你想跟大哥去美国", "他想跟你去美国", "你要去美国找大哥"]
    ↓
每个变体 → ASR 关键字搜索 + 字幕关键字搜索（字幕 2x 权重）
    ↓
选最高分匹配为"标准化"结果
    ↓
返回 {original, normalized, confident, matches}
```

### 置信度
- `confident=true`: ASR/字幕匹配分 ≥ 5
- `confident=false`: 无匹配，使用变体兜底

---

## 文件路径约定

```
VIBECAP/
├── {电视剧}/
│   ├── sources/epN/          ← 原始 API 产出
│   ├── sources_clean/epN/    ← 清洗后数据
│   ├── semantic_index.pkl    ← BGE 索引
│   ├── character_portraits/  ← 角色人脸
│   └── tasks/{任务}/         ← 剪辑任务
│
├── vibecap-server/
│   ├── analyze_episodes.py   ← Step 1
│   ├── clean_data.py         ← Step 2
│   ├── build_index.py        ← Step 3
│   └── server.py             ← 搜索服务
│
└── vibecap-web/              ← 前端
```

## 运行命令

```bash
# 分析新剧集（6秒高精度）
python3 analyze_episodes.py --ep 5 --segment 6

# 数据清洗
python3 clean_data.py

# 重建索引
python3 build_index.py

# 重启服务
python3 server.py --drama 都挺好 --task Task7029
```
