---
title: 语音识别ASR
type: topic
tags: [ai-model, technique, implemented]
difficulty: 中等
prerequisites: ["Python基础", "音频与ffmpeg基础"]
status: implemented
created: 2026-08-04
---

# 语音识别 (ASR)

> 自动语音识别 (Automatic Speech Recognition)：把视频里的说话声变成可搜索的中文文本。

## 是什么

ASR 就是把音频波形转换为文字。在 VibeCut 中，这是整个搜索系统的基础——你搜的不是视频本身，而是 ASR 转写出来的对话文本和 VLM 生成的画面描述文本。

```
视频 → 提取音频 → ASR 模型 → "苏明玉：你凭什么管我们家的事"
                                            ↓
                                    存入 asr_result.json
                                    带时间戳 {start: 12.5, end: 15.8, text: "..."}
                                            ↓
                                    索引入库 → 用户搜索时命中
```

## 为什么是本地 ASR 而不是云端 API

| 维度 | 本地 faster-whisper | 云端 API (如 Deepgram) |
|------|-------------------|----------------------|
| 费用 | 免费 | 按小时计费（46集≈100小时≈$50） |
| 隐私 | 视频不离开本机 | 上传到第三方服务器 |
| 离线 | 无需网络 | 需要稳定连接 |
| 速度 | CPU 推理 10-30x 实时 | 通常 2-5x 实时 |
| 质量 | small 模型≈云端 90% | 大模型略优 |

对个人项目来说，免费 + 隐私 > 多出的那 10% 准确率。

## 关键概念

### 1. faster-whisper 与 CTranslate2

`faster-whisper` 是 OpenAI Whisper 的 CTranslate2 重新实现，速度比原版快 4 倍，内存占用少一半。

```
OpenAI Whisper (原版)  →  10x 实时 (CPU)  →  46 集 ≈ 460 小时
faster-whisper         →  3-4x 实时 (CPU)  →  46 集 ≈ 138 小时
faster-whisper int8    →  2-3x 实时 (CPU)  →  46 集 ≈ 92 小时
```

CTranslate2 的核心优化：
- 算子融合：把多个矩阵运算合并成一步
- 内存布局优化：CPU 缓存友好的数据排列
- 图优化：移除推理图的冗余节点

### 2. Whisper 模型大小

| 模型 | 参数量 | 内存 | 速度 (CPU) | 准确率 | VibeCut 用在哪 |
|------|-------|------|-----------|--------|---------------|
| tiny | 39M | ~1GB | 最快 | 较低 | 快速测试 |
| base | 74M | ~1GB | 快 | 一般 | 口播采访 (`asr_narration.py`) |
| small | 244M | ~2GB | 中等 | 较好 | 电视剧 (`analyze_episodes.py`) |
| medium | 769M | ~5GB | 慢 | 很好 | 质量要求高的场景 |
| large-v3 | 1.5B | ~10GB | 很慢 | 最好 | 未使用 (CPU 太慢) |

选模型是在速度和准确率间权衡。VibeCut 的口播用 base（口播说话清晰，准确率够用）。**电视剧管线 v3.1 起改用网上下载 SRT 字幕，不再本地 whisper**（公网字幕质量 > 本地小模型），whisper 主要留给口播短片段。

### 3. int8 量化

```python
# faster-whisper 启用 int8 量化
from faster_whisper import WhisperModel
model = WhisperModel("small", device="cpu", compute_type="int8")
```

量化 = 把模型从 float32 (32位浮点数) 压缩到 int8 (8位整数)。模型体积减半，推理速度提升 30-50%，准确率下降不到 1%。

量化后的模型权重只有 256 种可能值（int8 = 0-255），而原版是 40 亿种（float32 = `±3.4 × 10³⁸`）。但巧妙的是，神经网络对精度的冗余度很高——这 1% 的精度损失几乎不可感知，但 40% 的速度提升非常明显。

### 4. VAD（Voice Activity Detection）

Whisper 模型内部自带 VAD：只处理有人声的音频段，跳过静音。这对于电视剧特别重要——一部剧里很多时间是没有对话的空镜。没有 VAD 的话，模型会在静音段浪费大量计算。

### 5. Speaker Diarization（说话人识别）

```
raw:       "你凭什么管我们家的事我来管我自己家的事"
diarized:  "主持人: 你凭什么管我们家的事"
           "嘉宾: 我来管我自己家的事"
```

在口播项目中，`clean_interview_data.py` 使用 LLM（DeepSeek）来标注说话人（guest/host），因为 faster-whisper 本身不支持 diarization。

说话人识别对索引质量至关重要：只有 guest（嘉宾）的 content 层发言才进入 BGE 索引，host（主持人）的引导语和问句不进入索引，避免搜索"学习方法"时匹配到"接下来请老师讲讲学习方法"这样的主持人套话。

## 在 VibeCut 中的应用

### 电视剧管线

**`cli/analyze_episodes.py`**（v3.1）：
- 电视剧管线改为**网上下载 SRT 字幕**（`subtitle_result.json`），不再本地 whisper ASR
- 字幕 → DeepSeek 场记 Agent（scene_map）→ VLM 画面分析

**`asr_narration.py`**：
- 更轻量的 ASR 脚本，用 `whisper base` 处理短片段旁白

### 口播管线

**`classify_transcript.py`**：
- 输入：原始 ASR JSON（`asr_*.json`）
- 输出：带四层分类的 `classified_*.json`
- 四层分类：content（干货内容）/ guide（引导过渡）/ meta（元评论）/ filler（废料）

**`clean_interview_data.py`**：
- 输入：classified 数据
- 输出：`classified_enhanced.json`（含说话人标注、清洗后文本）
- 说话人识别：LLM 根据语气和内容判断 guest / host

### 数据流转

```
电视剧:                                   口播:
网上下载 SRT 字幕 → subtitle_result.json    视频 → asr_narration.py (whisper base*)
     → analyze_episodes.py (场记+VLM)              → asr_*.json
     → cli/build_index.py (进入 BGE 索引)          → classify_transcript.py (LLM 四层分类)
                                                    → clean_interview_data.py (LLM 说话人+清洗)
                                                    → classified_enhanced.json
                                                    → cli/build_index.py (BGE, guest-only)
```

> *注：`asr_narration.py` 中的模型选择为 "base"，但在实际项目中口播 ASR 使用 faster-whisper。

## 动手实验

1. **用 faster-whisper 转写一段音频**

```bash
pip install faster-whisper
```

```python
from faster_whisper import WhisperModel

model = WhisperModel("tiny", device="cpu", compute_type="int8")
segments, info = model.transcribe("test_audio.wav", language="zh")

for seg in segments:
    print(f"[{seg.start:.1f}s → {seg.end:.1f}s] {seg.text}")
```

2. **观察不同模型大小的速度差异**

对同一段 1 分钟音频，分别用 tiny / base / small 转写，记录耗时和内存。

3. **了解 VAD 效果**

对比启用和禁用 VAD 时，模型对一段"30秒静音 + 30秒说话"音频的处理速度。

## 前置知识

- [[L1-语言与运行时]] — ffmpeg 音频提取

## 延伸

- [[大语言模型LLM]] — LLM 在 ASR 后处理中的角色（分类、清洗、说话人识别）
- [[视觉语言模型VLM]] — VLM 补充画面信息（不是对话信息）
- [[BGE索引实战]] — ASR 文本如何进入语义索引
- [[模型部署与优化]] — CPU 推理优化（int8、mmap）
