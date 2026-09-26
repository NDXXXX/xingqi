"""FastAPI 应用。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
from .api.characters import router as characters_router
from .api.conversations import router as conversations_router
from .api.mcp import router as mcp_router
from .api.memories import router as memories_router
from .api.providers import router as providers_router
from .api.skills import router as skills_router
from .database import models  # noqa: F401  # 注册 ORM 模型到 Base.metadata
from .database.db import Base, engine

app = FastAPI(title="Desktop AI Companion — Agent Runtime")

# 桌面渲染进程直接通过 HTTP 访问本后端（dev: localhost:5173 / prod: file://）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-runtime"}


app.include_router(conversations_router)
app.include_router(providers_router)
app.include_router(characters_router)
app.include_router(memories_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(chat_router)

# 本地单进程应用：启动时建表（幂等）。
Base.metadata.create_all(bind=engine)
