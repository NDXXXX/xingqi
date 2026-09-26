"""Chat API：非流式 /api/chat 与流式 /api/chat/stream（SSE），均走 Agent。"""

import json
import logging
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agent.context import build_tool_registry, with_agent_context
from ..agent.run_manager import active_runs
from ..agent.runtime import run_agent, run_agent_stream
from ..database.db import SessionLocal, get_db
from ..database.repositories.conversation_repository import ConversationRepository
from ..database.repositories.message_repository import MessageRepository
from ..database.repositories.identity_repository import IdentityRepository
from ..database.repositories.agent_run_repository import AgentRunRepository
from ..memory.manager import MemoryManager
from ..providers.router import provider_router
from ..providers.selection import ProviderSelectionError, select_provider_model
from .conversations import MessageOut
from .errors import classify_provider_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

conversation_repo = ConversationRepository()
message_repo = MessageRepository()
memory_manager = MemoryManager()
identity_repo = IdentityRepository()
run_repo = AgentRunRepository()

class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    provider_id: str | None = None
    model: str | None = None
    regenerate: bool = False


def _prepare(db: Session, req: ChatRequest):
    if req.conversation_id:
        conversation = conversation_repo.get(db, req.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = req.message.strip()[:30] or "New Chat"
        conversation = conversation_repo.create(
            db, title=title, channel="desktop", identity_id=identity_repo.local(db).id
        )
    if conversation.identity_id is None and conversation.channel == "desktop":
        conversation.identity_id = identity_repo.local(db).id
        db.commit()

    try:
        provider, model_config = select_provider_model(
            db, conversation, req.provider_id, req.model
        )
    except ProviderSelectionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    model = model_config.model_name

    existing_messages = message_repo.list_by_conversation(db, conversation.id)
    if not existing_messages and conversation.title == "New Chat":
        conversation.title = req.message.strip()[:30] or "New Chat"
        db.commit()
        db.refresh(conversation)

    if req.regenerate:
        user_message = message_repo.prepare_regeneration(db, conversation.id)
        if user_message is None:
            raise HTTPException(status_code=400, detail="没有可以重新生成的用户消息")
        req.message = user_message.content
    else:
        user_message = message_repo.create(
            db, conversation_id=conversation.id, role="user", content=req.message
        )

    history = message_repo.list_by_conversation(db, conversation.id)
    llm_messages = [{"role": m.role, "content": m.content} for m in history]

    llm_messages = with_agent_context(
        db,
        conversation,
        req.message,
        llm_messages,
        model_config.context_window,
        model_config.max_output_tokens,
    )

    user_message_out = MessageOut.model_validate(user_message).model_dump(mode="json")

    return conversation, provider, model, llm_messages, user_message_out


@router.post("")
async def chat(req: ChatRequest, db: Session = Depends(get_db)) -> dict:
    conversation, provider, model, llm_messages, user_message_out = _prepare(db, req)
    p = provider_router.get_provider(provider)
    registry = build_tool_registry()
    run = run_repo.create(db, conversation.id, provider.id, model)

    steps: list[dict] = []
    final_response = ""
    try:
        async for event in run_agent(p, registry, model, conversation.id, llm_messages):
            if event["type"] in {"step", "tool"}:
                steps.append(event)
                run_repo.add_event(db, run.id, event)
            elif event["type"] == "final":
                final_response = event["final_response"]
    except Exception as e:
        run_repo.finish(db, run.id, "failed", str(e))
        raise

    assistant = message_repo.create(db, conversation_id=conversation.id, role="assistant", content=final_response)
    conversation_repo.touch(db, conversation.id, model)
    try:
        await memory_manager.extract_and_save(
            db, p, model, req.message, final_response, conversation.identity_id
        )
    except Exception as e:
        logger.warning("memory extraction failed: %s", e)
    run_repo.finish(db, run.id, "completed")
    return {
        "run_id": run.id,
        "conversation_id": conversation.id,
        "user_message": user_message_out,
        "assistant_message": MessageOut.model_validate(assistant).model_dump(mode="json"),
        "steps": steps,
    }


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    conversation, provider, model, llm_messages, user_message_out = _prepare(db, req)
    p = provider_router.get_provider(provider)
    registry = build_tool_registry()
    conversation_id = conversation.id
    identity_id = conversation.identity_id
    run = run_repo.create(db, conversation.id, provider.id, model)
    run_id = run.id

    async def gen():
        session = SessionLocal()
        steps: list[dict] = []
        final_response = ""
        active_runs.register(run_id)
        try:
            yield f"data: {json.dumps({'type': 'run', 'run_id': run_id}, ensure_ascii=False)}\n\n"
            async for event in run_agent_stream(p, registry, model, conversation_id, llm_messages):
                if event["type"] in {"step", "tool"}:
                    steps.append(event)
                    run_repo.add_event(session, run_id, event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "chunk":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "final":
                    final_response = event["final_response"]
        except asyncio.CancelledError:
            run_repo.finish(session, run_id, "cancelled")
            active_runs.unregister(run_id)
            session.close()
            raise
        except GeneratorExit:
            run_repo.finish(session, run_id, "cancelled")
            active_runs.unregister(run_id)
            session.close()
            raise
        except Exception as e:
            run_repo.finish(session, run_id, "failed", str(e))
            active_runs.unregister(run_id)
            session.close()
            code, message, retryable, _status = classify_provider_error(e)
            error = {
                "code": code,
                "message": message,
                "retryable": retryable,
                "request_id": request.state.request_id,
            }
            yield f"data: {json.dumps({'type': 'error', 'detail': message, 'error': error}, ensure_ascii=False)}\n\n"
            return
        try:
            assistant = message_repo.create(session, conversation_id=conversation_id, role="assistant", content=final_response)
            conversation_repo.touch(session, conversation_id, model)
            try:
                await memory_manager.extract_and_save(
                    session, p, model, req.message, final_response, identity_id
                )
            except Exception as e:
                logger.warning("memory extraction failed: %s", e)
            assistant_out = MessageOut.model_validate(assistant).model_dump(mode="json")
            run_repo.finish(session, run_id, "completed")
            yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'conversation_id': conversation_id, 'user_message': user_message_out, 'assistant_message': assistant_out, 'steps': steps}, ensure_ascii=False)}\n\n"
        except Exception as e:
            run_repo.finish(session, run_id, "failed", str(e))
            raise
        finally:
            active_runs.unregister(run_id)
            session.close()

    return StreamingResponse(gen(), media_type="text/event-stream")
