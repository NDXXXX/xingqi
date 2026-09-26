"""MCP API。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database.db import get_db
from ..database.repositories.integration_repository import McpConfigRepository
from ..mcp.manager import default_manager

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
mcp_config_repo = McpConfigRepository()


class McpConnectRequest(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)


class McpDisconnectRequest(BaseModel):
    name: str


class McpServerOut(BaseModel):
    name: str
    command: str
    args: list[str]
    connected: bool
    tools: list[str]


@router.get("", response_model=list[McpServerOut])
def list_mcp(db: Session = Depends(get_db)) -> list[dict]:
    connected = {server["name"]: server for server in default_manager.servers()}
    return [
        connected.get(
            config.name,
            {
                "name": config.name,
                "command": config.command,
                "args": mcp_config_repo.args(config),
                "connected": False,
                "tools": [],
            },
        )
        for config in mcp_config_repo.list(db)
    ]


@router.post("/connect", response_model=list[McpServerOut])
async def connect_mcp(payload: McpConnectRequest, db: Session = Depends(get_db)) -> list[dict]:
    try:
        await default_manager.connect(payload.name, payload.command, payload.args)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接 MCP 服务器失败: {e}") from e
    mcp_config_repo.upsert(db, payload.name, payload.command, payload.args)
    return list_mcp(db)


@router.post("/disconnect", response_model=list[McpServerOut])
async def disconnect_mcp(payload: McpDisconnectRequest, db: Session = Depends(get_db)) -> list[dict]:
    await default_manager.disconnect(payload.name)
    mcp_config_repo.disable(db, payload.name)
    return list_mcp(db)
