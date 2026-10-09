"""Memory management endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Depends
from zhiyu.application.characters import CharacterService

from zhiyu.api.schemas.agent import MemoryEditBody
from zhiyu.application.memories import MemoryService


def build_memories_router(memories: MemoryService) -> APIRouter:
    router = APIRouter()

    def scoped(character_id: str | None = None):
        if character_id is not None and CharacterService(memories.session_factory).get(character_id) is None:
            raise HTTPException(404, "智能体不存在")
        return MemoryService(memories.session_factory, memories.store, character_id)

    @router.get("/api/memory-index-status")
    async def memory_index_status(service: MemoryService = Depends(scoped)):
        return service.index_status()

    @router.get("/api/memory-consolidation-runs")
    async def consolidation_runs(
        limit: int = Query(default=5, ge=1, le=20),
        offset: int = Query(default=0, ge=0),
        service: MemoryService = Depends(scoped),
    ):
        return service.consolidation_runs(limit, offset)

    @router.get("/api/memories")
    async def list_memories(
        query: str | None = Query(default=None),
        include_inactive: bool = False,
        tier: str | None = Query(default=None, pattern="^(core|episodic)$"),
        service: MemoryService = Depends(scoped),
    ):
        try:
            items = (
                service.search(query, include_inactive=include_inactive, tier=tier)
                if query
                else service.list(include_inactive=include_inactive, tier=tier)
            )
            return [asdict(item) for item in items]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/memories/clear")
    async def clear_memories(service: MemoryService = Depends(scoped)):
        return {"deleted": service.clear()}

    @router.patch("/api/memories/{memory_id}")
    async def edit_memory(memory_id: str, body: MemoryEditBody, service: MemoryService = Depends(scoped)):
        try:
            return asdict(service.edit(memory_id, content=body.content))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/memories/{memory_id}/confirm")
    async def confirm_memory(memory_id: str, service: MemoryService = Depends(scoped)):
        try:
            return asdict(service.confirm(memory_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/memories/{memory_id}/keep")
    async def keep_memory(memory_id: str, service: MemoryService = Depends(scoped)):
        try:
            return asdict(service.keep(memory_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/memories/{memory_id}", status_code=204)
    async def forget_memory(memory_id: str, service: MemoryService = Depends(scoped)):
        try:
            service.forget(memory_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return None

    return router
