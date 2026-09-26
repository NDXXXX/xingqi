"""FastAPI 应用。"""

from contextlib import asynccontextmanager
import asyncio
import hmac
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.errors import install_error_handlers
from .api.channels import router as channels_router
from .api.agent_runs import router as agent_runs_router
from .api.chat import router as chat_router
from .api.characters import router as characters_router
from .api.conversations import router as conversations_router
from .api.mcp import router as mcp_router
from .api.memories import router as memories_router
from .api.providers import router as providers_router
from .api.settings import router as settings_router
from .api.skills import router as skills_router
from .channels.manager import default_manager as channel_manager
from .config.keystore import keystore
from .config.logging import configure_logging
from .config.settings import settings
from .database import models  # noqa: F401  # 注册 ORM 模型到 Base.metadata
from .database.db import SessionLocal
from .database.migrations import upgrade_database
from .database.repositories.integration_repository import ChannelConfigRepository, McpConfigRepository
from .mcp.manager import default_manager as mcp_manager

logger = logging.getLogger(__name__)


async def restore_integrations() -> None:
    db = SessionLocal()
    try:
        channel_configs = [
            config
            for config in ChannelConfigRepository().list_enabled(db)
            if config.auto_connect
        ]
        mcp_repo = McpConfigRepository()
        mcp_configs = mcp_repo.list_auto_connect(db)
        operations = [
            channel_manager.connect(
                config.channel,
                config.endpoint,
                keystore.get(config.secret_ref) if config.secret_ref else None,
            )
            for config in channel_configs
        ] + [
            mcp_manager.connect(config.name, config.command, mcp_repo.args(config))
            for config in mcp_configs
        ]
        if operations:
            results = await asyncio.gather(*operations, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("integration auto-connect failed: %s", result)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    upgrade_database()
    await restore_integrations()
    yield
    await channel_manager.close_all()
    await mcp_manager.close_all()


app = FastAPI(title="Desktop AI Companion — Agent Runtime", lifespan=lifespan)
install_error_handlers(app)

# 桌面渲染进程直接通过 HTTP 访问本后端（dev: localhost:5173 / prod: file://）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-Companion-Token", "X-Request-ID"],
)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    if request.method != "OPTIONS" and settings.api_token and not hmac.compare_digest(
        request.headers.get("X-Companion-Token", ""), settings.api_token
    ):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "本地 API 访问令牌无效",
                    "retryable": False,
                    "request_id": request.state.request_id,
                }
            },
            headers={"X-Request-ID": request.state.request_id},
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-runtime"}


app.include_router(conversations_router)
app.include_router(agent_runs_router)
app.include_router(providers_router)
app.include_router(settings_router)
app.include_router(characters_router)
app.include_router(memories_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(channels_router)
app.include_router(chat_router)
