"""Chat, conversation and run endpoints."""

import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from zhiyu.api.schemas.agent import CharacterBody, ChatBody
from zhiyu.characters.service import CharacterService
from zhiyu.chat.service import ChatRequest
from zhiyu.sessions.service import ConversationService
from zhiyu.application.runtime import RuntimeHost
from zhiyu.memory.store import MemoryStore


def build_agent_router(runtime: RuntimeHost) -> APIRouter:
    router = APIRouter()
    conversations = ConversationService(runtime.chat_service.session_factory)
    memory_manager = runtime.chat_service.memory_processor.memory_manager
    memory_store = getattr(memory_manager, "store", None)
    if not isinstance(memory_store, MemoryStore):
        memory_store = None
    avatar_dir = memory_store.dir.parent / "avatars" if memory_store is not None else None
    characters = CharacterService(
        runtime.chat_service.session_factory,
        avatar_dir=avatar_dir,
        memory_store=memory_store,
    )
    if memory_store is not None:
        characters.recover_deletions(
            runtime.chat_service.session_factory, memory_store, characters.avatar_dir
        )

    @router.get("/api/agents")
    async def list_agents():
        return [asdict(item) for item in characters.list()]

    @router.post("/api/agents", status_code=201)
    async def create_agent(body: CharacterBody):
        try:
            return asdict(characters.create(**body.model_dump()))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/agents/{character_id}/template")
    async def export_agent_template(character_id: str):
        try:
            payload = characters.export_template(character_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return JSONResponse(
            payload,
            headers={"Content-Disposition": 'attachment; filename="xingqi-character.json"'},
        )

    @router.post("/api/agents/import", status_code=201)
    async def import_agent_template(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 4 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="角色模板不能超过 4 MiB")
        try:
            payload = json.loads(content)
            character, warning = characters.import_template(payload)
            return {"agent": asdict(character), "warning": warning}
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(400, str(exc) or "角色模板 JSON 无效") from exc

    @router.put("/api/agents/{character_id}")
    async def update_agent(character_id: str, body: CharacterBody):
        try:
            return asdict(characters.update(character_id, **body.model_dump()))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/api/agents/{character_id}")
    async def delete_agent(character_id: str):
        try:
            characters.delete(character_id)
            return {"deleted": True}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.put("/api/agents/{character_id}/avatar")
    async def upload_agent_avatar(character_id: str, request: Request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="头像不能超过 2 MiB")
        try:
            return asdict(characters.upload_avatar(character_id, content_type, bytes(content)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/agents/{character_id}/avatar")
    async def clear_agent_avatar(character_id: str):
        try:
            return asdict(characters.clear_avatar(character_id))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/api/agents/{character_id}/avatar")
    async def get_agent_avatar(character_id: str):
        path = characters.avatar_path(character_id)
        if path is None:
            raise HTTPException(status_code=404, detail="角色头像不存在")
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix)
        if media_type is None:
            raise HTTPException(status_code=404, detail="角色头像不存在")
        return FileResponse(path, media_type=media_type)

    @router.post("/api/chat")
    async def chat(body: ChatBody):
        if not body.regenerate and not body.message.strip():
            raise HTTPException(status_code=400, detail="消息不能为空")

        async def stream():
            try:
                async for event in runtime.chat_service.run(
                    ChatRequest(
                        message=body.message,
                        conversation_id=body.conversation_id,
                        provider_id=body.provider_id,
                        model=body.model,
                        character_id=body.character_id,
                        regenerate=body.regenerate,
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
    async def list_conversations(query: str | None = None, character_id: str | None = None, scoped: bool = False):
        if character_id and characters.get(character_id) is None:
            raise HTTPException(404, "智能体不存在")
        return conversations.list_conversations(query, character_id=character_id, scoped=scoped or character_id is not None)

    @router.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str):
        if not conversations.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"deleted": True}

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
