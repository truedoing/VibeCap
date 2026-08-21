---
title: HTTP服务与SSE流式
type: topic
tags: [infrastructure, technique, implemented]
difficulty: 入门
prerequisites: ["Python 标准库", "JavaScript fetch API"]
status: implemented
created: 2026-08-04
---

# HTTP 服务与 SSE 流式

> HTTP 与 SSE 原理 + VibeCut 现状：早期用标准库 http.server 理解底层，v1.1 后 HTTP 层演进到 FastAPI，SSE 统一走 lib/sse.py。

## 是什么

**HTTP 服务**：监听某个端口（如 8765），接收浏览器发来的 HTTP 请求，处理后返回响应。

**SSE（Server-Sent Events）**：服务器"推送"数据给浏览器的协议。传统 HTTP 是"请求-响应"模式（浏览器问一句，服务器答一句），SSE 是服务器主动、持续地向浏览器发送数据流。适合 AI 生成内容这种"不知道什么时候生成完"的场景。

```
传统 HTTP:                        SSE 流式:
浏览器 ──req──→ 服务器             浏览器 ──req──→ 服务器
浏览器 ←──res── 服务器             浏览器 ←──"正在策划..."── 服务器
                                 浏览器 ←──"正在搜索素材..."── 服务器
                                 浏览器 ←──"正在生成脚本..."── 服务器
                                 浏览器 ←──"done"── 服务器
```

## 为什么从 http.server 出发（原理课）

几个关键原因：

1. **零依赖**：`http.server` 和 `socketserver` 是 Python 自带标准库。服务器端唯一需要的第三方库是 `sentence-transformers` 和 `numpy`（用于AI功能），不需要额外安装 Web 框架。

2. **理解底层**：Flask 的 `@app.route("/search")` 魔术般的装饰器背后，本质上就是 `if path == "/search": ...` 的 if/elif 链条。用标准库写一遍，你就永远理解了 Web 框架在做什么。

3. **控制力**：SSE 流式输出时，你需要精细控制什么时候 `flush()`、什么时候断开连接。标准库让你完全掌控，框架反而会多加一层抽象。

4. **历史演进**：VibeCut 早期确实用 http.server 单文件（`server.py`），v1.1 重构为 FastAPI（`main.py` + `routers/`），但「先懂底层再用框架」的原则不变——这一篇的 http.server 例子，就是 FastAPI 帮你做的事。

## 关键概念

### 1. ThreadingMixIn — 多请求并发

```python
from http.server import HTTPServer
from socketserver import ThreadingMixIn

class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True  # 主线程退出时，工作线程自动退出
```

`HTTPServer` 默认是单线程的：处理一个请求时，其他请求排队等待。`ThreadingMixIn` 让每个请求跑在独立线程里 —— 当你同时打开编剧台和分镜台时，两个页面的请求互不阻塞。

### 2. do_GET / do_POST 路由

这是早期 http.server 时代的写法（v1.1 前）。现在 FastAPI 用 `app.include_router()` 注册（`main.py` L30-46），一个请求进 router → handler 分发。理解 if/elif 版，才能看懂框架替你做了什么：

```python
def do_GET(self):
    if path == "/search":
        self._json(self._search(q, mode=mode))
    elif path == "/segments.json":
        # 先从 SQLite 查，再从文件兜底
        ...
    elif path == "/proxies/manifest":
        self._serve_proxy_manifest()
    ...

def do_POST(self):
    if path == "/script/generate_script_stream":
        self._handle_generate_script_stream()  # SSE 流式
    elif path == "/script/refine":
        self._handle_refine()  # 精切 SSE 流式
    ...
```

没有装饰器、没有路由注册表、没有中间件。所有的逻辑在文件里一字排开，对于学习来说是极好的起点。

### 3. SSE 原理（早期 http.server 的 wfile 实现）

```python
# 发送 SSE 响应头
self.send_response(200)
self.send_header("Content-Type", "text/event-stream")
self.send_header("Cache-Control", "no-cache")
self.send_header("Connection", "keep-alive")
self.send_header("Access-Control-Allow-Origin", "*")
self.end_headers()

# 发送事件
def emit(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    self.wfile.write(msg.encode("utf-8"))
    self.wfile.flush()  # 立即发送，不缓冲

# 阶段 1: 策划
emit("progress", {"stage": "planning", "percent": 10, "detail": "分析主题..."})
# 阶段 2: 搜索
emit("progress", {"stage": "searching", "percent": 30, "detail": "BGE语义搜索..."})
# 阶段 3: 生成
emit("result", {"segments": [...], "done": True})

# 流结束
emit("done", {"ok": True})
```

关键细节：**`self.wfile.flush()`**。没有这行，Python 会缓冲输出，浏览器收不到任何数据，直到缓冲区满或请求结束 —— 那就不叫"流式"了。

**现在的实现见 `lib/sse.py` 的 `sse_stream()`**：后台线程跑任务、队列缓冲、生成器逐步 `yield`（见 [[Python-标准库与并发]]），`flush` 的原理不变。

### 4. 浏览器端接收 SSE

在 React 前端，用 `fetch` + reader 消费（VibeCut 的 SSE 全是 POST，`EventSource` 不支持 POST）：

```javascript
// 使用 fetch + ReadableStream（比 EventSource 更灵活，支持 POST）
const response = await fetch("/script/generate_script_stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ topic: "学习的本质", task: "0801" }),
})

const reader = response.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  const text = decoder.decode(value)
  // 解析 "event: progress\ndata: {...}\n\n" 格式
  // 更新 UI 进度条
}
```

## 在 VibeCut 中的应用（当前）

**SSE 统一实现**：`lib/sse.py` — `sse_stream()`（后台线程 + 队列缓冲 + 生成器 yield），后端所有 SSE 端点复用；`make_emitter()` 提供 progress/complete/error 三回调。

**HTTP 层**：`main.py` L30-46 注册 13 个 router；`routers/` 按功能域拆分。

**流式端点清单**：

| 端点 | 用途 |
|------|------|
| `/script/generate_drama_script_v2`（`routers/sse_script.py`） | drama 脚本生成 |
| `/voiceover/generate_stream`（`routers/sse_voiceover.py`） | 一键全量配音 |
| `/voiceover/regenerate_segment`（`routers/sse_voiceover.py`） | 单段配音 |

> 早期 http.server 时代的端点（`/script/generate_script_stream`、`/script/generate_story_first`、`/script/refine`）已在 v1.1 重构中移除。

## 动手实验

1. **写一个最小的 SSE 服务器**（20行）

```python
import time, json
from http.server import HTTPServer, BaseHTTPRequestHandler

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(10):
            msg = f"data: {json.dumps({'count': i, 'ts': time.time()})}\n\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()
            time.sleep(0.5)

HTTPServer(("localhost", 8765), SSEHandler).serve_forever()
```

2. **用浏览器 DevTools 观察**：打开 `http://localhost:8765`，看 Network 面板中 SSE 请求的 EventStream 标签页。

3. **尝试去掉 `flush()`**：注释掉 `self.wfile.flush()`，观察浏览器是否还是"逐个收到"数据，还是"等10条一起收到"。

## 前置知识

- [[L1-语言与运行时]] — Python http.server 和 socketserver 标准库
- [[JavaScript与React生态]] — 浏览器端 fetch API

## 延伸

- [[SQLite数据层设计]] — 服务端如何持久化任务和分段数据
- [[Agent核心概念]] — Agent 流式输出的核心是 SSE
- [[React与Vite]] — 前端如何通过 Vite 代理消费后端 SSE
- [[LangGraph框架]] — LangGraph 内置 streaming 支持，本质就是 SSE
