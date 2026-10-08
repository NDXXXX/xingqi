"""Memory management endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query

from zhiyu.api.schemas.agent import MemoryEditBody
from zhiyu.application.memories import MemoryService


def build_memories_router(memories: MemoryService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/memory-index-status")
    async def memory_index_status():
        return memories.index_status()

    @router.get("/api/memory-consolidation-runs")
    async def consolidation_runs(
        limit: int = Query(default=5, ge=1, le=20),
        offset: int = Query(default=0, ge=0),
    ):
        return memories.consolidation_runs(limit, offset)

    @router.get("/api/memories")
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

    @router.patch("/api/memories/{memory_id}")
    async def edit_memory(memory_id: str, body: MemoryEditBody):
        try:
            return asdict(memories.edit(memory_id, content=body.content))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/memories/{memory_id}/confirm")
    async def confirm_memory(memory_id: str):
        try:
            return asdict(memories.confirm(memory_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/memories/{memory_id}/keep")
    async def keep_memory(memory_id: str):
        try:
            return asdict(memories.keep(memory_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/memories/{memory_id}", status_code=204)
    async def forget_memory(memory_id: str):
        try:
            memories.forget(memory_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return None

    return router
