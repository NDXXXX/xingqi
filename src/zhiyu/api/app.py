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
    async def local_admin_only(request: Request, call_next):
        admin_prefixes = (
            "/api/providers", "/api/mcp/servers", "/api/skills",
            "/api/qq/", "/api/channel-events/", "/api/channel-deliveries/",
        )
        if request.url.path.startswith(admin_prefixes) and request.method not in {"GET", "HEAD", "OPTIONS"}:
            host = request.client.host if request.client else ""
            try:
                is_local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_local = host in {"localhost", "testclient"}
            if not is_local:
                return JSONResponse(status_code=403, content={"detail": "管理操作仅允许本机访问"})
            host_header = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
            host_header = host_header.lower()
            try:
                valid_host = host_header in {"localhost", "testserver"} or ipaddress.ip_address(host_header).is_loopback
            except ValueError:
                valid_host = False
            if not valid_host:
                return JSONResponse(status_code=403, content={"detail": "管理操作 Host 无效"})
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                parsed = urlsplit(origin)
                request_host = request.headers.get("host", "").lower()
                if parsed.netloc.lower() != request_host or parsed.scheme not in {"http", "https"}:
                    return JSONResponse(status_code=403, content={"detail": "管理操作来源与页面不一致"})
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return runtime.health()

    static_dir = Path(__file__).parents[1] / "web" / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app
