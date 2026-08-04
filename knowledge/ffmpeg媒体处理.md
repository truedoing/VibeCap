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

> VibeCut 的视频处理全靠 ffmpeg/ffprobe 命令行 — 不是 Python 库，是独立进程调用

## 是什么

ffmpeg 是音视频处理的瑞士军刀。在 VibeCut 中，它通过 `subprocess.run()` 调用，处理所有视频/音频相关操作。

## VibeCut 中的四大场景

### 1. 代理视频生成
1080p 原片 → 540p 轻量代理，供浏览器流畅播放：
```
ffmpeg -i 原片.mp4 -vf scale=960:540 -crf 28 -preset fast -g 50 -c:a aac -b:a 64k 代理.mp4
```
参数含义：960×540 分辨率 / CRF 28 画质 / 快速编码 / 每 50 帧一个关键帧

### 2. 音频提取
为 ASR 准备 16kHz 单声道音频：
```
ffmpeg -i 视频.mp4 -vn -ar 16000 -ac 1 音频.wav
```

### 3. 片段导出
从原片精确裁剪片段：
```
ffmpeg -ss 120.5 -t 8.3 -i 原片.mp4 -c:v libx264 -preset ultrafast -crf 18 片段.mp4
```

### 4. 时长探测
用 ffprobe 获取视频时长（无需解码）：
```
ffprobe -v quiet -show_entries format=duration -of csv=p=0 视频.mp4
```

## 关键概念

- **CRF (画质):** 0=无损, 18=视觉无损, 28=可接受压缩
- **Preset (速度):** ultrafast→fast→medium→slow, 越慢压缩率越高
- **GOP (关键帧间隔):** 影响拖动精度，越小越精确但文件越大

## 在 VibeCut 中的应用

| 模块 | ffmpeg 用途 |
|------|-----------|
| `generate_proxies.py` | 批量生成代理视频 |
| `analyze_episodes.py` | 音频提取 + 场景切分 |
| `export_capcut.py` | 精切片段导出 |
| `extract_concat.py` | 视频拼接 |

## 动手实验

```bash
# 提取一段 5 秒的视频片段
ffmpeg -ss 60 -t 5 -i 视频.mp4 -c copy 片段.mp4
# 获取视频信息
ffprobe -v quiet -print_format json -show_format 视频.mp4
```
