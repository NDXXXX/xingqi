"""Memory management endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query

from zhiyu.api.schemas.agent import MemoryEditBody
from zhiyu.application.memories import MemoryService


def build_memories_router(memories: MemoryService) -> APIRouter:
    router = APIRouter()

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

    return router
