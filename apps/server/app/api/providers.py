"""Provider API。"""

from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config.keystore import keystore
from ..database.db import get_db
from ..database.models import AgentRun, Character, Conversation, Provider
from ..database.repositories.provider_repository import ProviderRepository
from ..database.repositories.setting_repository import SettingRepository
from ..providers.router import PROVIDER_SPECS, provider_router
from .settings import DEFAULT_MODEL_KEY

router = APIRouter(prefix="/api/providers", tags=["providers"])

provider_repo = ProviderRepository()
setting_repo = SettingRepository()


class ModelConfigOut(BaseModel):
    id: str
    model_name: str
    display_name: str
    supports_tools: bool
    supports_streaming: bool
    enabled: bool
    context_window: int | None
    max_output_tokens: int | None

    model_config = ConfigDict(from_attributes=True)


class ProviderOut(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str | None
    enabled: bool
    configured: bool
    models: list[ModelConfigOut]

    model_config = ConfigDict(from_attributes=True)


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None


class ModelConfigCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    supports_tools: bool = True
    supports_streaming: bool = True
    enabled: bool = True
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)


class ModelConfigUpdate(BaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    enabled: bool | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)


@router.get("", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db)) -> list[Provider]:
    return provider_repo.list(db)


@router.post("", response_model=ProviderOut, status_code=201)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> Provider:
    if payload.provider_type not in PROVIDER_SPECS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider_type: {payload.provider_type}")

    if provider_repo.get_by_name(db, payload.name.strip()):
        raise HTTPException(status_code=409, detail="Provider 名称已存在")

    # API Key 写入 Keychain，DB 只存 ref。
    api_key_ref = None
    if payload.api_key:
        api_key_ref = str(uuid4())
        keystore.set(api_key_ref, payload.api_key)

    return provider_repo.create(
        db,
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        api_key_ref=api_key_ref,
        base_url=payload.base_url,
    )


@router.patch("/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: str, payload: ProviderUpdate, db: Session = Depends(get_db)
) -> Provider:
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    changes = payload.model_dump(exclude_unset=True)

    if "name" in changes:
        name = changes["name"].strip()
        duplicate = provider_repo.get_by_name(db, name)
        if duplicate is not None and duplicate.id != provider.id:
            raise HTTPException(status_code=409, detail="Provider 名称已存在")
        changes["name"] = name

    if "api_key" in changes:
        api_key = changes.pop("api_key")
        old_ref = provider.api_key_ref
        if api_key:
            new_ref = str(uuid4())
            keystore.set(new_ref, api_key)
            changes["api_key_ref"] = new_ref
        else:
            changes["api_key_ref"] = None
        provider = provider_repo.update(db, provider, **changes)
        if old_ref:
            keystore.delete(old_ref)
        return provider

    return provider_repo.update(db, provider, **changes)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str, db: Session = Depends(get_db)) -> None:
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    model_ids = [model.id for model in provider.models]
    model_names = [model.model_name for model in provider.models]
    if model_ids and db.scalars(select(Character).where(Character.default_model_id.in_(model_ids))).first():
        raise HTTPException(status_code=409, detail="Provider 仍被 Character 使用")
    if model_names and db.scalars(select(Conversation).where(Conversation.model_id.in_(model_names))).first():
        raise HTTPException(status_code=409, detail="Provider 仍被 Conversation 使用")
    if db.scalars(select(AgentRun).where(AgentRun.provider_id == provider.id)).first():
        raise HTTPException(status_code=409, detail="Provider 仍被 Agent Run 使用")
    default_model = setting_repo.get(db, DEFAULT_MODEL_KEY)
    if default_model and default_model.get("provider_id") == provider.id:
        raise HTTPException(status_code=409, detail="Provider 是当前默认模型")

    api_key_ref = provider.api_key_ref
    provider_repo.delete(db, provider)
    if api_key_ref:
        keystore.delete(api_key_ref)


@router.post("/{provider_id}/models", response_model=ModelConfigOut, status_code=201)
def create_model(
    provider_id: str, payload: ModelConfigCreate, db: Session = Depends(get_db)
):
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if any(model.model_name == payload.model_name for model in provider.models):
        raise HTTPException(status_code=409, detail="模型名称已存在")
    return provider_repo.create_model(db, provider, **payload.model_dump())


@router.patch("/{provider_id}/models/{model_id}", response_model=ModelConfigOut)
def update_model(
    provider_id: str,
    model_id: str,
    payload: ModelConfigUpdate,
    db: Session = Depends(get_db),
):
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    model = provider_repo.get_model(db, provider.id, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    changes = payload.model_dump(exclude_unset=True)
    if "model_name" in changes and any(
        item.id != model.id and item.model_name == changes["model_name"] for item in provider.models
    ):
        raise HTTPException(status_code=409, detail="模型名称已存在")
    return provider_repo.update_model(db, model, **changes)


@router.delete("/{provider_id}/models/{model_id}", status_code=204)
def delete_model(provider_id: str, model_id: str, db: Session = Depends(get_db)) -> None:
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    model = provider_repo.get_model(db, provider.id, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if db.scalars(select(Character).where(Character.default_model_id == model.id)).first():
        raise HTTPException(status_code=409, detail="模型仍被 Character 使用")
    if db.scalars(select(Conversation).where(Conversation.model_id == model.model_name)).first():
        raise HTTPException(status_code=409, detail="模型仍被 Conversation 使用")
    default_model = setting_repo.get(db, DEFAULT_MODEL_KEY)
    if default_model and default_model.get("model_id") == model.id:
        raise HTTPException(status_code=409, detail="模型是当前默认模型")
    provider_repo.delete_model(db, model)


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str, db: Session = Depends(get_db)) -> dict:
    provider = provider_repo.get(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    p = provider_router.get_provider(provider)
    if p.api_key is None:
        return {"ok": False, "detail": "未配置 API Key"}
    if not provider.models:
        return {"ok": False, "detail": "未配置模型"}

    model = provider.models[0].model_name
    try:
        reply = (await p.chat(messages=[{"role": "user", "content": "ping"}], model=model)).content
        return {"ok": True, "detail": "connected", "reply": reply}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "detail": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}
