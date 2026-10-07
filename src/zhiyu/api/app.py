"""只复用应用服务的本地 FastAPI 接口。"""

from contextlib import asynccontextmanager
from pathlib import Path
import ipaddress
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from zhiyu.api.routes.agent import build_agent_router
from zhiyu.api.routes.channels import build_channels_router
from zhiyu.api.routes.mcp import build_mcp_router
from zhiyu.api.routes.memories import build_memories_router
from zhiyu.api.routes.providers import build_provider_router
from zhiyu.api.routes.skills import build_skills_router
from zhiyu.application.memories import MemoryService
from zhiyu.application.providers import ProviderService
from zhiyu.application.runtime import RuntimeHost
from zhiyu.application.skills import SkillService


def create_app(host: RuntimeHost | None = None) -> FastAPI:
    runtime = host or RuntimeHost()
    session_factory = runtime.chat_service.session_factory
    memory_manager = runtime.chat_service.memory_processor.memory_manager
    store = getattr(memory_manager, "store", None)
    memories = MemoryService(session_factory, store=store)
    providers = ProviderService(session_factory, router=runtime.chat_service.providers)
    skills = SkillService(session_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="知语", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.include_router(build_provider_router(providers))
    app.include_router(build_mcp_router(runtime))
    app.include_router(build_skills_router(runtime, skills))
    app.include_router(build_channels_router(runtime))
    app.include_router(build_agent_router(runtime))
    app.include_router(build_memories_router(memories))

    @app.middleware("http")
    async def local_api_only(request: Request, call_next):
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            peer = request.client.host if request.client else ""
            try:
                local_peer = ipaddress.ip_address(peer).is_loopback
            except ValueError:
                local_peer = peer == "testclient"
            if not local_peer:
                return JSONResponse(status_code=403, content={"detail": "API 仅允许本机访问"})

            try:
                host_header = urlsplit(f"//{request.headers.get('host', '')}")
                host = (host_header.hostname or "").lower()
                host_port = host_header.port
                local_host = host == "localhost" or ipaddress.ip_address(host).is_loopback
            except ValueError:
                return JSONResponse(status_code=403, content={"detail": "API Host 无效"})
            if (
                not local_host or host_header.username or host_header.password
                or host_header.path or host_header.query or host_header.fragment
            ):
                return JSONResponse(status_code=403, content={"detail": "API Host 无效"})

            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
                if origin is not None or referer is not None:
                    try:
                        source = urlsplit(origin if origin is not None else referer)
                        source_port = source.port
                        default_port = 443 if request.url.scheme == "https" else 80
                        same_origin = (
                            source.scheme == request.url.scheme
                            and (source.hostname or "").lower() == host
                            and (source_port or default_port) == (host_port or default_port)
                            and not source.username and not source.password
                        )
                    except ValueError:
                        same_origin = False
                    if not same_origin:
                        return JSONResponse(status_code=403, content={"detail": "API 来源与页面不一致"})
                if request.headers.get("X-Zhiyu-Request") != "1":
                    return JSONResponse(status_code=403, content={"detail": "缺少本机请求标记"})
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return runtime.health()

    static_dir = Path(__file__).parents[1] / "web" / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app
