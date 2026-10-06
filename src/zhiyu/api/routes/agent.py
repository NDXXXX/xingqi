"""Chat, conversation and run endpoints."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from zhiyu.api.schemas.agent import ChatBody
from zhiyu.application.chat import ChatRequest
from zhiyu.application.runtime import RuntimeHost
from zhiyu.core.agent.run_manager import active_runs
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _step_value(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def build_agent_router(runtime: RuntimeHost) -> APIRouter:
    router = APIRouter()
    session_factory = runtime.chat_service.session_factory
    conversations = ConversationRepository()
    messages = MessageRepository()
    runs = AgentRunRepository()

    @router.post("/api/chat")
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
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        if not active_runs.cancel(run_id):
            raise HTTPException(status_code=404, detail="运行不存在或已经结束")
        return {"cancelled": True}

    @router.get("/api/conversations")
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

    @router.get("/api/conversations/{conversation_id}/messages")
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

    @router.get("/api/runs/{run_id}")
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

    return router
