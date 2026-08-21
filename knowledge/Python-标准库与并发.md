---
title: Python-标准库与并发
type: topic
tags: [language, infrastructure, implemented]
difficulty: 入门
prerequisites: ["Python基础"]
status: implemented
created: 2026-08-19
---

# Python 标准库与并发

> 不装框架也能干活——标准库怎么撑起 VibeCut 的文件、命令、后台任务和 HTTP

## 是什么

Python 自带「电池」——标准库不用 `pip install` 就能干很多事。这一篇讲 VibeCut 高频用的四个：**pathlib**（文件路径）、**subprocess**（调外部命令）、**threading**（后台任务）、**http.server**（HTTP 原理）。

> **注意**：VibeCut 现在的 HTTP 层用 FastAPI（`main.py`），但理解 http.server 才能看懂 FastAPI 替你做了什么——这正符合 [[L1-语言与运行时|L1 的原则]]：先懂底层机制，再用框架提速。

## pathlib：路径是对象，不是字符串

```python
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent    # 当前文件的上上级目录
sources_dir = project_dir / "sources"      # 用 / 拼接路径
if sources_dir.exists():                   # 判断存在
    ...
for d in sources_dir.iterdir():            # 遍历目录
    if d.is_dir() and d.name.startswith("ep"):
        ...
```

- `Path / "子目录"` 代替字符串的 `os.path.join`
- `iterdir()` 遍历、`exists()` 判断、`.name` 取文件名

**VibeCut 里：** `cli/build_index.py` L14 `ROOT_DIR = Path(__file__).parent.parent`，L26-29 用 `iterdir` + `startswith` 扫出全部集数目录。

## subprocess：在 Python 里调外部命令

Python 调 ffmpeg、调其他 Python 脚本，靠 subprocess 开子进程：

```python
p = subprocess.Popen(
    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, env=env,
)
for line in p.stdout:        # 逐行读输出（能实时解析进度）
    ...
p.wait(timeout=600)          # 等子进程结束；超时抛 TimeoutExpired
```

- `stdout=subprocess.PIPE` 捕获输出，`text=True` 按文本读
- `p.stdout` 逐行迭代 = 实时拿到子进程日志
- `p.wait(timeout=...)`：用 `except subprocess.TimeoutExpired` 处理超时

**VibeCut 里：** `lib/subprocess_runner.py` L45-70——统一子进程执行器，代理视频生成、抽帧、VLM 分析全走它；L115 还用正则解析 `12/20` 进度实时回传前端。

## threading：后台任务与共享状态

HTTP 请求不能干等几十分钟的流水线——丢进后台线程，请求立刻返回：

```python
_process_tasks: dict = {}
_process_lock = threading.Lock()

def _run_all():
    try:
        _run(0, "analyze_episodes.py", eps_args, timeout=3600)
        _run(1, "build_index.py", ["--project", drama_name], timeout=300)
    except Exception as e:
        print(f"[pipeline] 流水线异常: {e}")

threading.Thread(target=_run_all, daemon=True).start()   # 后台线程，主线程立即返回
```

- `threading.Thread(target=fn).start()`：fn 在后台线程跑，主线程继续
- `daemon=True`：主程序退出时后台线程自动结束，不会卡住进程
- 多线程共享 `_process_tasks` dict 必须加锁：`with _process_lock:` 保证读写不冲突

**VibeCut 里：** `handlers/pipeline.py` L12 锁 + L42 后台线程跑整条流水线；`lib/sse.py` L107/L124 也用线程发心跳、跑生成任务。

## http.server：不装框架也能起 HTTP（原理课）

VibeCut 现在用 FastAPI，但「HTTP 服务最小长什么样」必须懂：

```python
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = '{"ok": true}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

HTTPServer(("0.0.0.0", 8765), Handler).serve_forever()
```

- 一个请求 = 一次 `do_GET` / `do_POST` 回调
- 响应 = 状态码 + 头 + 正文
- **FastAPI 替你做了什么**：路由匹配、参数解析、JSON 序列化、CORS、OpenAPI 文档……所以 `main.py` 才那么短

**VibeCut 里：** 对比 `vibecut-server/main.py` L21-46——注册 13 个 router 就到这。VibeCut 历史上也用 http.server 起过服务，后来重构成 FastAPI。

## async/await：为什么 SSE 需要异步（概念引入）

流式响应（配音进度、脚本逐字生成）要「边算边发」，不能等全部算完再返回。Python 的 `async def`/`await` 让单线程在等待 I/O 时让出控制权。但 VibeCut 的 SSE 实现更朴素——用**线程 + 队列**把生成结果逐步 `yield` 出去：

```python
q = queue.Queue()

def _run():                 # 后台线程跑业务，emit 结果进队列
    inner_fn(*args, _emit)
threading.Thread(target=_run, daemon=True).start()

while True:
    chunk = q.get()         # 生成器从队列取一条发一条
    if chunk is None: break
    yield chunk
```

- 好处：不依赖 asyncio 也能流式；生成器 `yield` 一次发一条 SSE
- 深入学 async/await（真正的异步模型）→ 看 [[HTTP服务与SSE流式]]

**VibeCut 里：** `lib/sse.py` L92-130 `sse_stream()`——线程跑任务、队列缓冲、生成器 yield，后端所有 SSE 端点复用这一个。

## 在 VibeCut 中的应用

| 标准库 | 干什么 | 文件 |
|--------|--------|------|
| pathlib | 项目 / 任务目录路径 | `cli/build_index.py` L14 |
| subprocess | 调 ffmpeg / 脚本子进程 | `lib/subprocess_runner.py` L45 |
| threading | 后台流水线 / SSE 心跳 | `handlers/pipeline.py` L42、`lib/sse.py` L107 |
| queue | 线程间传数据 | `lib/sse.py` L92 |
| http.server | HTTP 原理课（现用 FastAPI） | 对比 `main.py` L21 |

## 前置知识

- [[Python基础]] — 函数 / 模块 / 异常是这篇的前置

## 延伸

- [[HTTP服务与SSE流式]] — SSE 的 async 深入
- [[SQLite数据层设计]] — 数据落库（标准库 `sqlite3`）

## 动手实验

1. 用 `pathlib.Path` 遍历 `都挺好/sources/`，打印所有 `ep*` 目录名。
2. 用 subprocess 调 ffmpeg 抽一帧（参考 `cli/extract_scene_frames.py` 的调用方式）。
3. 用 http.server 起一个返回 JSON 的迷你服务，浏览器访问看响应头和正文。
