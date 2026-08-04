---
title: ffmpeg媒体处理
type: topic
tags: [infrastructure, technique, implemented]
difficulty: 入门
prerequisites: []
status: implemented
created: 2026-08-04
---

# ffmpeg 媒体处理

> `ffmpeg` 是命令行界的瑞士军刀——转码、剪辑、提取音频、生成代理视频，VibeCut 的整个视频管线都靠它。

## 是什么

**ffmpeg** 是一个开源的音视频处理工具，能处理几乎所有格式的视频和音频。它没有 GUI，完全通过命令行操作。

**ffprobe** 是配套的媒体信息查看工具——不处理视频，只读取元数据（分辨率、时长、编码格式、帧率）。

VibeCut 中所有涉及视频文件的操作都是通过 `subprocess` 调用 ffmpeg/ffprobe CLI 完成的，没有使用 Python 绑定库。

## 为什么用 CLI 而非 Python 库

| Python 库（如 `ffmpeg-python`） | CLI 直接调用 |
|---|---|
| 多一层封装，有学习成本 | 直接写 ffmpeg 命令，所见即所得 |
| 库版本和 ffmpeg 版本可能不兼容 | 系统装什么版本就用什么版本 |
| 调试困难（库内部的命令构造是黑盒） | 复制日志中的命令直接终端重跑 |
| 部分高级参数不支持 | 所有 ffmpeg 参数都能用 |

VibeCut 选 CLI 直接调用的核心理由：**可调试性**。当 `extract_clip` 失败时，日志里打印的 ffmpeg 命令可以直接复制到终端重跑，定位问题是参数问题还是文件问题。

## 关键概念

### 1. 代理视频生成

```bash
ffmpeg -y -hide_banner -loglevel error \
  -i 原视频1080p.mp4 \
  -vf "scale=960:540,fps=25" \
  -c:v libx264 -preset fast -crf 28 \
  -g 50 -keyint_min 50 -pix_fmt yuv420p \
  -c:a aac -b:a 64k \
  输出_540p.mp4
```

参数详解（对应 `generate_proxies.py` 第 69-79 行）：

| 参数 | 值 | 作用 |
|------|-----|------|
| `scale` | 960:540 | 分辨率降到 1/4（1080p→540p），浏览器播放轻量 |
| `fps` | 25 | 统一帧率，避免剪辑时帧对齐问题 |
| `-c:v` | libx264 | 视频编码器（兼容性最好的 H.264） |
| `-preset` | fast | 编码速度优先（不做极致压缩） |
| `-crf` | 28 | 画质（0=无损，51=最差），28 是视觉可接受的底线 |
| `-g` / `-keyint_min` | 50 | GOP 大小（每 2 秒一个关键帧），保证 seek 精度 |
| `-pix_fmt` | yuv420p | 像素格式（浏览器兼容性最好） |
| `-c:a` | aac | 音频编码器 |
| `-b:a` | 64k | 音频码率（单声道语音够用） |

**GOP 为什么重要？** GOP（Group of Pictures）= 两个关键帧之间的帧数。GOP=50 意味着每 2 秒（25fps）就有一个完整帧。这对于剪辑场景至关重要——如果 GOP 太大（比如 250=10 秒），seek 到某个位置可能要等 10 秒才能解码出画面。

### 2. 音频提取（供 ASR 使用）

```bash
ffmpeg -y -hide_banner -loglevel error \
  -i 原视频.mp4 \
  -vn -acodec pcm_s16le -ar 16000 -ac 1 \
  输出.wav
```

| 参数 | 值 | 作用 |
|------|-----|------|
| `-vn` | 无 | 丢弃视频流 |
| `-acodec` | pcm_s16le | 无损 PCM 格式（ASR 模型需要） |
| `-ar` | 16000 | 采样率 16kHz（Whisper 标准输入） |
| `-ac` | 1 | 单声道（语音识别不需要立体声） |

### 3. 素材片段提取

```bash
ffmpeg -y -hide_banner -loglevel error \
  -ss 10.5 -t 3.2 \
  -i 原视频.mp4 \
  -c:v libx264 -preset ultrafast -crf 18 \
  -c:a aac -b:a 256k \
  -movflags +faststart \
  片段输出.mp4
```

关键参数：

| 参数 | 说明 |
|------|------|
| `-ss 10.5` | 从 10.5 秒处开始（放在 `-i` 之前 = 快速 seek） |
| `-t 3.2` | 截取 3.2 秒 |
| `-preset ultrafast` | 最快编码（片段短，无所谓压缩率） |
| `-crf 18` | 高质量（成片要用，不能像代理那样压到 28） |
| `-movflags +faststart` | moov atom 前置（浏览器可边下边播） |

对应 `export_capcut.py` 的 `extract_clip()` 函数。

### 4. ffprobe 元数据读取

```bash
ffprobe -v quiet -print_format json -show_format -show_streams 视频.mp4
```

返回 JSON 格式的完整媒体信息：时长、分辨率、编码格式、码率、帧率等。VibeCut 在代理视频生成前先用 ffprobe 确认源视频存在且可读。

## 在 VibeCut 中的应用

**`generate_proxies.py`**：
- 扫描源视频目录 → ffprobe 读取元数据 → ffmpeg 转码为 540p → 生成 `.proxies_manifest.json`
- 支持批量模式（`--all`）、选集模式（`--ep 1,3,5`）、区间模式（`--ep 1-10`）

**`analyze_episodes.py`**（电视剧管线）：
- ffmpeg 提取音频为 16kHz WAV → 喂给 faster-whisper 做 ASR

**`export_capcut.py`**：
- `extract_clip()` 用 ffmpeg 切割精确的视频片段 → 作为剪映草稿的素材

**`server.py`**：
- `/preview_video` 端点：根据时间范围动态切割视频片段返回前端预览

## 前置知识

无需特定前置知识，但建议有基本的命令行操作经验。

## 延伸

- [[视频编辑引擎Elah]] — 代理视频在浏览器中的播放
- [[语音识别ASR]] — 提取的 16kHz WAV 喂给 Whisper
- [[模型部署与优化]] — 速度和性能的权衡（类似 CRF 的 trade-off）

## 动手实验

1. **用 ffprobe 查看一个视频的信息**
```bash
ffprobe -v quiet -print_format json -show_format -show_streams 视频文件.mp4 | python3 -m json.tool
```

2. **手动生成一个代理视频**
```bash
ffmpeg -i 你的视频.mp4 -vf "scale=960:540,fps=25" \
  -c:v libx264 -preset fast -crf 28 -g 50 \
  -c:a aac -b:a 64k 输出_540p.mp4
# 对比文件大小：ls -lh 原视频.mp4 输出_540p.mp4
```

3. **提取 5 秒片段**
```bash
ffmpeg -ss 30 -t 5 -i 你的视频.mp4 \
  -c:v libx264 -preset ultrafast -crf 18 \
  -c:a aac -b:a 256k 片段.mp4
```

## 学习资源

- ffmpeg 官方文档 (ffmpeg.org) — 完整的参数手册
- `generate_proxies.py` 源码 — VibeCut 的实战参数配置
- ffmpeg Wiki: H.264 Encoding Guide — CRF 和 preset 的详细说明
