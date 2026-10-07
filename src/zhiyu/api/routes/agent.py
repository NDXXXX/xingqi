"""Chat, conversation and run endpoints."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from zhiyu.api.schemas.agent import ChatBody
from zhiyu.application.chat import ChatRequest
from zhiyu.application.conversations import ConversationService
from zhiyu.application.runtime import RuntimeHost


def build_agent_router(runtime: RuntimeHost) -> APIRouter:
    router = APIRouter()
    conversations = ConversationService(runtime.chat_service.session_factory)

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
        if not conversations.cancel_run(run_id):
            raise HTTPException(status_code=404, detail="运行不存在或已经结束")
        return {"cancelled": True}

    @router.get("/api/conversations")
    async def list_conversations(query: str | None = None):
        return conversations.list_conversations(query)

    @router.get("/api/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str):
        history = conversations.history(conversation_id)
        if history is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return history

    @router.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        detail = conversations.run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        return detail

    return router
