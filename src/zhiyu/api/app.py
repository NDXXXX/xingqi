"""只复用应用服务的本地 FastAPI 接口。"""

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from zhiyu.application.chat import ChatRequest
from zhiyu.application.memories import MemoryService
from zhiyu.application.providers import ProviderService
from zhiyu.application.runtime import RuntimeHost
from zhiyu.core.agent.run_manager import active_runs
from zhiyu.infrastructure.database.repositories.agent_run_repository import (
    AgentRunRepository,
)
from zhiyu.infrastructure.database.repositories.conversation_repository import (
    ConversationRepository,
)
from zhiyu.infrastructure.database.repositories.message_repository import (
    MessageRepository,
)


class ChatBody(BaseModel):
    message: str
    conversation_id: str | None = None
    provider_id: str | None = None
    model: str | None = None


class MemoryEditBody(BaseModel):
    content: str


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _step_value(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def create_app(host: RuntimeHost | None = None) -> FastAPI:
    runtime = host or RuntimeHost()
    session_factory = runtime.chat_service.session_factory
    memory_manager = runtime.chat_service.memory_processor.memory_manager
    store = getattr(memory_manager, "store", None)
    memories = MemoryService(session_factory, store=store)
    providers = ProviderService(session_factory, router=runtime.chat_service.providers)
    conversations = ConversationRepository()
    messages = MessageRepository()
    runs = AgentRunRepository()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="知语", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/api/health")
    async def health():
        return runtime.health()

    @app.post("/api/chat")
    async def chat(body: ChatBody):
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="消息不能为空")

        async def stream():
            try:
                async for event in runtime.chat_service.run(
                    ChatRequest(
                        message=body.message,
                        conversation_id=body.conversation_id,
                        provider_id=body.provider_id,
                        model=body.model,
                    )
                ):
                    yield f"data: {_json(event)}\n\n"
            except Exception as exc:
                yield f"data: {_json({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        if not active_runs.cancel(run_id):
            raise HTTPException(status_code=404, detail="运行不存在或已经结束")
        return {"cancelled": True}

    @app.get("/api/conversations")
    async def list_conversations(query: str | None = None):
        with session_factory() as db:
            return [
                {
                    "id": item.id,
                    "title": item.title,
                    "channel": item.channel,
                    "model_id": item.model_id,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in conversations.list(db, query)
            ]

    @app.get("/api/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str):
        with session_factory() as db:
            if conversations.get(db, conversation_id) is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            return [
                {
                    "id": item.id,
                    "role": item.role,
                    "content": item.content,
                    "created_at": item.created_at,
                }
                for item in messages.list_by_conversation(db, conversation_id)
            ]

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        with session_factory() as db:
            run = runs.get(db, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="运行不存在")
            return {
                "id": run.id,
                "conversation_id": run.conversation_id,
                "provider_id": run.provider_id,
                "model_id": run.model_id,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "error": run.error,
                "steps": [
                    {
                        "id": step.id,
                        "type": step.step_type,
                        "name": step.name,
                        "status": step.status,
                        "input": _step_value(step.input_json),
                        "output": _step_value(step.output_json),
                        "error": step.error,
                    }
                    for step in run.steps
                ],
            }

    @app.get("/api/memories")
    async def list_memories(
        query: str | None = Query(default=None),
        include_inactive: bool = False,
        tier: str | None = Query(default=None, pattern="^(core|episodic)$"),
    ):
        try:
            items = (
                memories.search(query, include_inactive=include_inactive, tier=tier)
                if query
                else memories.list(include_inactive=include_inactive, tier=tier)
            )
            return [asdict(item) for item in items]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/memories/{memory_id}")
    async def edit_memory(memory_id: str, body: MemoryEditBody):
        try:
            return asdict(memories.edit(memory_id, content=body.content))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/providers")
    async def list_providers():
        return [asdict(item) for item in providers.list()]

    @app.get("/api/channels")
    async def list_channels():
        return runtime.channel_manager.list()

    @app.get("/api/channel-events")
    async def list_channel_events(limit: int = Query(default=50, ge=1, le=200)):
        return runtime.channel_service.list_events(limit)

    @app.get("/api/qq/groups")
    async def list_qq_groups():
        return runtime.channel_service.list_group_policies()

    @app.get("/api/channel-deliveries")
    async def list_channel_deliveries(limit: int = Query(default=50, ge=1, le=200)):
        return runtime.channel_service.list_deliveries(limit)

    static_dir = Path(__file__).parents[1] / "web" / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app
