"""应用级设置 API。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database.db import get_db
from ..database.repositories.provider_repository import ProviderRepository
from ..database.repositories.setting_repository import SettingRepository

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULT_MODEL_KEY = "default_model"
setting_repo = SettingRepository()
provider_repo = ProviderRepository()


class DefaultModel(BaseModel):
    provider_id: str | None = None
    model_id: str | None = None


@router.get("/default-model", response_model=DefaultModel)
def get_default_model(db: Session = Depends(get_db)) -> DefaultModel:
    value = setting_repo.get(db, DEFAULT_MODEL_KEY)
    return DefaultModel.model_validate(value or {})


@router.put("/default-model", response_model=DefaultModel)
def set_default_model(payload: DefaultModel, db: Session = Depends(get_db)) -> DefaultModel:
    if payload.provider_id is None and payload.model_id is None:
        setting_repo.delete(db, DEFAULT_MODEL_KEY)
        return payload
    if not payload.provider_id or not payload.model_id:
        raise HTTPException(status_code=400, detail="provider_id 与 model_id 必须同时提供")
    provider = provider_repo.get(db, payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    model = provider_repo.get_model(db, provider.id, payload.model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    setting_repo.set(db, DEFAULT_MODEL_KEY, payload.model_dump())
    return payload
