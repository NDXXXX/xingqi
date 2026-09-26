"""Memory API。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..database.db import get_db
from ..database.models import Memory
from ..database.repositories.memory_repository import MemoryRepository
from ..memory.extractor import MEMORY_TYPES

router = APIRouter(prefix="/api/memories", tags=["memories"])

memory_repo = MemoryRepository()


class MemoryCreate(BaseModel):
    type: str
    content: str
    importance: float = 0.5


class MemoryUpdate(BaseModel):
    type: str | None = None
    content: str | None = None
    importance: float | None = None


class MemoryOut(BaseModel):
    id: str
    user_id: str | None
    type: str
    content: str
    importance: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[MemoryOut])
def list_memories(db: Session = Depends(get_db)) -> list[Memory]:
    return memory_repo.list(db)


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(payload: MemoryCreate, db: Session = Depends(get_db)) -> Memory:
    if payload.type not in MEMORY_TYPES:
        raise HTTPException(status_code=400, detail=f"无效 type: {payload.type}")
    return memory_repo.create(db, type=payload.type, content=payload.content, importance=payload.importance)


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, payload: MemoryUpdate, db: Session = Depends(get_db)) -> Memory:
    memory = memory_repo.get(db, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("type") is not None and updates["type"] not in MEMORY_TYPES:
        raise HTTPException(status_code=400, detail=f"无效 type: {updates['type']}")
    return memory_repo.update(db, memory, **updates)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: Session = Depends(get_db)) -> None:
    if not memory_repo.delete(db, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
