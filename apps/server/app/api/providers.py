"""Provider API。"""

from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..config.keystore import keystore
from ..database.db import get_db
from ..database.models import Provider
from ..database.repositories.provider_repository import ProviderRepository
from ..providers.router import PROVIDER_SPECS, provider_router

router = APIRouter(prefix="/api/providers", tags=["providers"])

provider_repo = ProviderRepository()


class ModelConfigOut(BaseModel):
    id: str
    model_name: str
    display_name: str
    supports_tools: bool
    supports_streaming: bool
    enabled: bool

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
    name: str
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None


@router.get("", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db)) -> list[Provider]:
    return provider_repo.list(db)


@router.post("", response_model=ProviderOut, status_code=201)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> Provider:
    if payload.provider_type not in PROVIDER_SPECS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider_type: {payload.provider_type}")

    # API Key 写入 Keychain，DB 只存 ref。
    api_key_ref = None
    if payload.api_key:
        api_key_ref = str(uuid4())
        keystore.set(api_key_ref, payload.api_key)

    return provider_repo.create(
        db,
        name=payload.name,
        provider_type=payload.provider_type,
        api_key_ref=api_key_ref,
        base_url=payload.base_url,
    )


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
