"""Channels API。"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..channels.manager import default_manager
from ..config.keystore import keystore
from ..database.db import get_db
from ..database.repositories.integration_repository import ChannelConfigRepository

router = APIRouter(prefix="/api/channels", tags=["channels"])
channel_config_repo = ChannelConfigRepository()


class ChannelOut(BaseModel):
    channel: str
    connected: bool
    status: str
    last_connected_at: str | None = None
    last_disconnected_at: str | None = None
    last_error: str | None = None
    retry_count: int = 0


class ChannelConnect(BaseModel):
    ws_url: str
    access_token: str | None = None


@router.get("", response_model=list[ChannelOut])
def list_channels() -> list[dict]:
    return default_manager.list()


@router.post("/{channel}/connect", response_model=list[ChannelOut])
async def connect_channel(
    channel: str, payload: ChannelConnect, db: Session = Depends(get_db)
) -> list[dict]:
    config = channel_config_repo.get(db, channel)
    secret_ref = config.secret_ref if config else None
    access_token = payload.access_token
    if access_token:
        new_ref = str(uuid4())
        keystore.set(new_ref, access_token)
        old_ref = secret_ref
        secret_ref = new_ref
    elif secret_ref:
        access_token = keystore.get(secret_ref)
        old_ref = None
    else:
        old_ref = None
    try:
        await default_manager.connect(channel, payload.ws_url, access_token)
    except ValueError as e:
        if payload.access_token and secret_ref:
            keystore.delete(secret_ref)
        raise HTTPException(status_code=400, detail=str(e)) from e
    channel_config_repo.upsert(db, channel, payload.ws_url, secret_ref)
    if old_ref:
        keystore.delete(old_ref)
    return default_manager.list()


@router.post("/{channel}/disconnect", response_model=list[ChannelOut])
async def disconnect_channel(channel: str, db: Session = Depends(get_db)) -> list[dict]:
    await default_manager.disconnect(channel)
    channel_config_repo.disable(db, channel)
    return default_manager.list()
