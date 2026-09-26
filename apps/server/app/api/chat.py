"""Chat API：非流式 /api/chat 与流式 /api/chat/stream（SSE），均走 Agent。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agent.runtime import run_agent
from ..characters.prompts import build_system_prompt
from ..database.db import SessionLocal, get_db
from ..database.models import Provider
from ..database.repositories.character_repository import CharacterRepository
from ..database.repositories.conversation_repository import ConversationRepository
from ..database.repositories.message_repository import MessageRepository
from ..database.repositories.provider_repository import ProviderRepository
from ..providers.router import provider_router
from ..tools.registry import default_registry
from .conversations import MessageOut

router = APIRouter(prefix="/api/chat", tags=["chat"])

conversation_repo = ConversationRepository()
message_repo = MessageRepository()
provider_repo = ProviderRepository()
character_repo = CharacterRepository()

# 最终答案在 SSE 里的分块大小（skeleton：agent loop 非流式，最终答案分块下发以保留打字机效果）。
CHUNK_SIZE = 24


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    provider_id: str | None = None
    model: str | None = None


def _resolve_provider(db: Session, provider_id: str | None) -> Provider:
    if provider_id:
        provider = provider_repo.get(db, provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Provider not found")
    else:
        provider = next((p for p in provider_repo.list(db) if p.enabled and p.configured), None)
    if provider is None:
        raise HTTPException(status_code=400, detail="没有可用的 Provider，请先在 Settings 配置")
    return provider


def _resolve_model(provider: Provider, model: str | None) -> str:
    if model:
        return model
    if provider.models:
        return provider.models[0].model_name
    raise HTTPException(status_code=400, detail="Provider 未配置模型")


def _prepare(db: Session, req: ChatRequest):
    provider = _resolve_provider(db, req.provider_id)
    model = _resolve_model(provider, req.model)

    if req.conversation_id:
        conversation = conversation_repo.get(db, req.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = req.message.strip()[:30] or "New Chat"
        conversation = conversation_repo.create(db, title=title, channel="desktop")

    user_message = message_repo.create(db, conversation_id=conversation.id, role="user", content=req.message)

    history = message_repo.list_by_conversation(db, conversation.id)
    llm_messages = [{"role": m.role, "content": m.content} for m in history]
    if conversation.character_id:
        character = character_repo.get(db, conversation.character_id)
        if character is not None:
            llm_messages.insert(0, {"role": "system", "content": build_system_prompt(character)})
    user_message_out = MessageOut.model_validate(user_message).model_dump(mode="json")

    return conversation, provider, model, llm_messages, user_message_out


def _chunk(text: str):
    return [text[i : i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]


@router.post("")
async def chat(req: ChatRequest, db: Session = Depends(get_db)) -> dict:
    conversation, provider, model, llm_messages, user_message_out = _prepare(db, req)
    p = provider_router.get_provider(provider)
    registry = default_registry()

    steps: list[dict] = []
    final_response = ""
    async for event in run_agent(p, registry, model, conversation.id, llm_messages):
        if event["type"] == "step":
            steps.append(event)
        elif event["type"] == "final":
            final_response = event["final_response"]

    assistant = message_repo.create(db, conversation_id=conversation.id, role="assistant", content=final_response)
    conversation_repo.touch(db, conversation.id, model)
    return {
        "conversation_id": conversation.id,
        "user_message": user_message_out,
        "assistant_message": MessageOut.model_validate(assistant).model_dump(mode="json"),
        "steps": steps,
    }


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    conversation, provider, model, llm_messages, user_message_out = _prepare(db, req)
    p = provider_router.get_provider(provider)
    registry = default_registry()
    conversation_id = conversation.id

    async def gen():
        steps: list[dict] = []
        final_response = ""
        try:
            async for event in run_agent(p, registry, model, conversation_id, llm_messages):
                if event["type"] == "step":
                    steps.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "final":
                    final_response = event["final_response"]
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"
            return
        for part in _chunk(final_response):
            yield f"data: {json.dumps({'type': 'chunk', 'text': part}, ensure_ascii=False)}\n\n"
        # 独立会话：流结束后 get_db 会话可能已随请求关闭。
        session = SessionLocal()
        try:
            assistant = message_repo.create(session, conversation_id=conversation_id, role="assistant", content=final_response)
            conversation_repo.touch(session, conversation_id, model)
            assistant_out = MessageOut.model_validate(assistant).model_dump(mode="json")
        finally:
            session.close()
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation_id, 'user_message': user_message_out, 'assistant_message': assistant_out, 'steps': steps}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
