"""MCP API。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..mcp.manager import default_manager

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class McpConnectRequest(BaseModel):
    name: str
    command: str
    args: list[str] = []


class McpDisconnectRequest(BaseModel):
    name: str


class McpServerOut(BaseModel):
    name: str
    command: str
    args: list[str]
    connected: bool
    tools: list[str]


@router.get("", response_model=list[McpServerOut])
def list_mcp() -> list[dict]:
    return default_manager.servers()


@router.post("/connect", response_model=list[McpServerOut])
async def connect_mcp(payload: McpConnectRequest) -> list[dict]:
    try:
        await default_manager.connect(payload.name, payload.command, payload.args)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接 MCP 服务器失败: {e}") from e
    return default_manager.servers()


@router.post("/disconnect", response_model=list[McpServerOut])
async def disconnect_mcp(payload: McpDisconnectRequest) -> list[dict]:
    await default_manager.disconnect(payload.name)
    return default_manager.servers()
