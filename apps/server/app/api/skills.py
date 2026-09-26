"""Skills API。"""

from fastapi import APIRouter

from ..skills.registry import Skill, default_registry

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[Skill])
def list_skills() -> list[Skill]:
    return default_registry.all()


@router.post("/reload", response_model=list[Skill])
def reload_skills() -> list[Skill]:
    return default_registry.reload()
