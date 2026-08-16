"""可复用的 SSE (Server-Sent Events) 发射器 + 流式生成器

v1.1 — 提取 main.py 的 _sse_gen() 为通用 sse_stream()，消除 5 处重复代码。
"""

import json
import threading
import time
import queue
from typing import Callable


def sse_headers():
    """返回 SSE 所需的响应头字典"""
    return {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
    }


def create_emitter(send_fn: Callable):
    """创建 emit 函数，适配不同框架的发送方式

    用于 http.server:
        def emit(event, data):
            self.wfile.write(f"event: {event}\\ndata: {json.dumps(data)}\\n\\n".encode())
            self.wfile.flush()

    用于 FastAPI StreamingResponse:
        async def emit(event, data):
            yield f"event: {event}\\ndata: {json.dumps(data)}\\n\\n"
    """
    def emit(event: str, data: dict):
        send_fn(event, data)
    return emit


def start_heartbeat(emit_fn: Callable, interval: float = 15.0) -> list:
    """启动 SSE 心跳线程，返回 [active_flag]

    用法:
        heartbeat_active = start_heartbeat(emit)
        try:
            ...  # SSE 主逻辑
        finally:
            heartbeat_active[0] = False
    """
    heartbeat_active = [True]

    def _beat():
        while heartbeat_active[0]:
            time.sleep(interval)
            try:
                emit_fn("heartbeat", {"ts": time.time()})
            except Exception:
                break

    threading.Thread(target=_beat, daemon=True).start()
    return heartbeat_active


def make_emitter(emit):
    """把 sse_stream 的 emit(event, data) 适配成 handler 惯用的三回调。

    返回 (emit_progress, emit_complete, emit_error)，消除各 SSE 端点手写三件套的重复。
    """
    def emit_progress(step, msg, data=None):
        emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
    def emit_complete(result):
        emit("complete", result)
    def emit_error(error, detail=""):
        emit("error", {"error": error, "detail": detail})
    return emit_progress, emit_complete, emit_error


def sse_stream(inner_fn, *args):
    """通用 SSE 生成器 — 消除 main.py 中 5 处重复的 _sse_gen 模式。

    用法:
        def my_work(task_name, emit):
            emit("progress", {"msg": "starting"})
            ...
            emit("complete", {"ok": True})

        return StreamingResponse(
            sse_stream(my_work, task_name),
            media_type="text/event-stream"
        )
    """
    q = queue.Queue()

    def _emit(event, data):
        q.put(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")

    heartbeat_active = [True]

    def _heartbeat():
        while heartbeat_active[0]:
            time.sleep(15)
            try:
                q.put(f"event: heartbeat\ndata: {json.dumps({'ts': time.time()})}\n\n")
            except Exception:
                break

    threading.Thread(target=_heartbeat, daemon=True).start()

    def _run():
        try:
            inner_fn(*args, _emit)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                _emit("error", {"error": str(e)[:200]})
            except Exception:
                pass
        finally:
            time.sleep(0.5)
            heartbeat_active[0] = False
            q.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    while True:
        chunk = q.get()
        if chunk is None:
            break
        yield chunk
