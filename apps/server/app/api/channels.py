"""Channels API。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..channels.manager import default_manager

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelOut(BaseModel):
    channel: str
    connected: bool


class ChannelConnect(BaseModel):
    ws_url: str
    access_token: str | None = None


@router.get("", response_model=list[ChannelOut])
def list_channels() -> list[dict]:
    return default_manager.list()


@router.post("/{channel}/connect", response_model=list[ChannelOut])
async def connect_channel(channel: str, payload: ChannelConnect) -> list[dict]:
    try:
        await default_manager.connect(channel, payload.ws_url, payload.access_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return default_manager.list()


@router.post("/{channel}/disconnect", response_model=list[ChannelOut])
async def disconnect_channel(channel: str) -> list[dict]:
    await default_manager.disconnect(channel)
    return default_manager.list()
