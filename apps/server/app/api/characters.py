"""Character API。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..database.db import get_db
from ..database.models import Character
from ..database.repositories.character_repository import CharacterRepository

router = APIRouter(prefix="/api/characters", tags=["characters"])

character_repo = CharacterRepository()


class CharacterCreate(BaseModel):
    name: str
    avatar: str | None = None
    description: str | None = None
    personality: str | None = None
    background: str | None = None
    speaking_style: str | None = None
    system_prompt: str | None = None
    default_model_id: str | None = None


class CharacterUpdate(BaseModel):
    name: str | None = None
    avatar: str | None = None
    description: str | None = None
    personality: str | None = None
    background: str | None = None
    speaking_style: str | None = None
    system_prompt: str | None = None
    default_model_id: str | None = None


class CharacterOut(BaseModel):
    id: str
    name: str
    avatar: str | None
    description: str | None
    personality: str | None
    background: str | None
    speaking_style: str | None
    system_prompt: str | None
    default_model_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[CharacterOut])
def list_characters(db: Session = Depends(get_db)) -> list[Character]:
    return character_repo.list(db)


@router.post("", response_model=CharacterOut, status_code=201)
def create_character(payload: CharacterCreate, db: Session = Depends(get_db)) -> Character:
    return character_repo.create(db, **payload.model_dump())


@router.get("/{character_id}", response_model=CharacterOut)
def get_character(character_id: str, db: Session = Depends(get_db)) -> Character:
    character = character_repo.get(db, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


@router.patch("/{character_id}", response_model=CharacterOut)
def update_character(
    character_id: str, payload: CharacterUpdate, db: Session = Depends(get_db)
) -> Character:
    character = character_repo.get(db, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return character_repo.update(db, character, **payload.model_dump(exclude_unset=True))


@router.delete("/{character_id}", status_code=204)
def delete_character(character_id: str, db: Session = Depends(get_db)) -> None:
    if not character_repo.delete(db, character_id):
        raise HTTPException(status_code=404, detail="Character not found")
