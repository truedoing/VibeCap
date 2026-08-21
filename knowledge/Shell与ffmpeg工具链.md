---
title: Shell与ffmpeg工具链
type: topic
tags: [language, infrastructure, implemented]
difficulty: 入门
prerequisites: ["L1-语言与运行时"]
status: implemented
created: 2026-08-20
---

# Shell 与 ffmpeg 工具链

> 命令行拼起来干大事——Bash 脚本 + ffmpeg 视频处理，VibeCut 的工具链

## 是什么

VibeCut 不只 Python——启动、构建、视频处理离不开 Shell 和 ffmpeg。这一篇讲两件事：

- **Bash**：把命令拼成脚本，自动化启动 / 构建（`start.sh`）
- **ffmpeg**：视频转码 / 抽帧的瑞士军刀（Python 用 subprocess 调它）

ffmpeg 本身的参数细节见 [[ffmpeg媒体处理]]，这里只讲「在 VibeCut 里怎么用」。

## Bash 够用就行

```bash
DRAMA=${1:-都挺好}       # 位置参数 $1，带默认值
TASK=${2:-Task7024}
PORT=${3:-8766}

cd "$(dirname "$0")"     # 切到脚本所在目录（相对路径更稳）
if [ -f .env ]; then     # if 判断文件存在
  export $(grep -v '^#' .env | xargs)   # 管道：读 .env 去注释 → 转环境变量
fi
```

- `$1/$2/$3`：位置参数；`${1:-默认值}` 取不到就用默认
- `[ -f 文件 ]`：文件存在判断；`if ... then ... fi` 是分支
- 管道 `|`：前一个命令的输出接给下一个；`grep -v '^#'` 过滤注释行
- `export`：设为环境变量，传给子进程

**VibeCut 里：** `vibecut-server/start.sh`——一键启动脚本，把 drama/task/port 位置参数、`.env` 加载、前端构建一次做完，最后 `python3 main.py` 起后端。

## ffmpeg 核心：转码

代理视频生成（1080p 原片 → 540p 代理）是 ffmpeg 最典型的用法：

```bash
ffmpeg -y -hide_banner -loglevel error \
  -i 都挺好_01_1080p.mp4 \
  -vf "scale=960:540,fps=24" \
  -c:v libx264 -preset fast -crf 23 \
  -pix_fmt yuv420p \
  -c:a aac -b:a 128k -ac 1 \
  -movflags +faststart \
  out.mp4
```

逐段解读：

- `-i 输入`：输入文件
- `-vf "scale=960:540,fps=24"`：缩放 + 帧率（代理瘦身的核心）
- `-c:v libx264 -preset fast -crf 23`：H.264 编码，crf 控制质量
- `-pix_fmt yuv420p`：兼容性像素格式
- `-c:a aac -b:a 128k -ac 1`：音频编码 / 码率 / 单声道
- `-movflags +faststart`：边下边播

**VibeCut 里：** `cli/generate_proxies.py` L70-83——46 集 1080p 压成 540p 代理，PR 风格源检视器播放的就是它。Python 侧用 `subprocess.run(cmd, capture_output=True)` 执行并检查退出码。

## ffmpeg 抽帧

给 VLM 视觉分析抽关键帧：

```bash
ffmpeg -y -ss 62 -i 都挺好_01_540p.mp4 -frames:v 1 -q:v 3 scene_012_0.jpg
```

- `-ss 62`：跳到第 62 秒
- `-frames:v 1`：只输出 1 帧
- `-q:v 3`：JPEG 质量（越小越清晰）

**VibeCut 里：** `cli/extract_scene_frames.py` L67——按 scene_map 的时间范围等分采样（取 1/3、2/3 位置避开切点边界），给 VLM 抽帧。

## 在 VibeCut 中的应用

| 工具 | 干什么 | 文件 |
|------|--------|------|
| Bash `start.sh` | 一键启动 + .env 加载 + 前端构建 | `vibecut-server/start.sh` |
| ffmpeg 转码 | 1080p → 540p 代理视频 | `cli/generate_proxies.py` L70 |
| ffmpeg 抽帧 | 关键帧提取给 VLM | `cli/extract_scene_frames.py` L67 |

## 前置知识

- [[L1-语言与运行时]] — Shell 是 L1 工具链的一环

## 延伸

- [[ffmpeg媒体处理]] — ffmpeg 参数和视频原理深入
- [[Python-标准库与并发]] — Python 用 subprocess 调 ffmpeg 的方式
- [[JavaScript与React生态]] — 前端 `npm run build` 构建

## 动手实验

1. 跑 `./vibecut-server/start.sh 都挺好 Task7024 8766`，观察脚本各段输出。
2. 用 ffmpeg 把任意视频抽一帧（参考 `cli/extract_scene_frames.py` 的命令格式）。
3. 写一个 5 行 bash 脚本，遍历 `都挺好/sources/ep*/` 打印每个目录的 `scene_map.json` 是否存在。
