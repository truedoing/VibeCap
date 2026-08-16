"""VibeCut Server v1.4 — FastAPI 入口 (瘦入口, 路由分发到 routers/)

drama编剧Agent + interview编剧台 + 导演Agent分镜匹配 + 配音台
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import args


@asynccontextmanager
async def lifespan(app: FastAPI):
    from routers._lifespan import startup, shutdown
    from config import args as _args
    startup(app, _args)
    yield
    shutdown()


app = FastAPI(title="VibeCut API", version="1.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册所有 Router ──
from routers import search, task_crud, segments, media, ai, sse_script, sse_voiceover, pipeline, export, picks, static
from routers.asr import router as asr_router

app.include_router(search.router)
app.include_router(task_crud.root_router)       # /dramas, /tasks (根路径)
app.include_router(task_crud.crud_router)       # /tasks/* CRUD
app.include_router(segments.router)
app.include_router(asr_router)                   # /asr
app.include_router(media.router)
app.include_router(ai.router)                  # /script, /chat, /dialogue_match, /storyboard_suggest
app.include_router(sse_script.router)          # /script SSE
app.include_router(sse_voiceover.router)       # /voiceover SSE
app.include_router(pipeline.router)            # /data
app.include_router(export.router)              # /export
app.include_router(picks.router)
app.include_router(static.router)              # SPA fallback (must be last)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
