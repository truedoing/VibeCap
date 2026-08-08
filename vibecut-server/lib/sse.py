"""可复用的 SSE (Server-Sent Events) 发射器 + 心跳"""

import json
import threading
import time
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
