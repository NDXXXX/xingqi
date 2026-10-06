"""MCP management endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from zhiyu.api.schemas.integrations import (
    McpAllowlistBody,
    McpCreateBody,
    McpEnabledBody,
    McpEnvBody,
    McpPromptBody,
    McpReadBody,
    McpSecretBody,
)
from zhiyu.application.runtime import RuntimeHost


def build_mcp_router(runtime: RuntimeHost) -> APIRouter:
    router = APIRouter()
    service = runtime.mcp_service

    @router.get("/api/mcp/servers")
    async def list_mcp_servers():
        return [asdict(item) for item in service.list()]

    @router.get("/api/mcp/servers/{name}/tools")
    async def list_mcp_tools(name: str):
        try:
            config = service.get(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        connection = runtime.mcp_manager.connection(name)
        allowed = set(config["tool_allowlist"])
        return [
            {
                "name": tool.name.removeprefix(f"{name}."),
                "description": tool.description,
                "schema": tool.schema,
                "enabled": config["legacy_all_tools"] or tool.name.removeprefix(f"{name}.") in allowed,
            }
            for tool in (getattr(connection, "discovered_tools", connection.tools) if connection else [])
        ]

    @router.post("/api/mcp/servers")
    async def configure_mcp(body: McpCreateBody):
        try:
            return asdict(service.configure(
                body.name, body.command, body.args, transport=body.transport,
                url=body.url, enabled=body.enabled,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/mcp/servers/{name}")
    async def get_mcp(name: str):
        try:
            return service.web_detail(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/api/mcp/servers/{name}/env")
    async def set_mcp_env(name: str, body: McpEnvBody):
        try:
            service.set_env(name, body.key, body.value, secret=body.secret)
            return service.web_detail(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/mcp/servers/{name}/header-secret")
    async def set_mcp_header_secret(name: str, body: McpSecretBody):
        try:
            service.set_header_secret(name, body.name, body.value)
            return service.web_detail(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/mcp/servers/{name}/tools/allowlist")
    async def set_mcp_tool_allowlist(name: str, body: McpAllowlistBody):
        try:
            service.set_tool_allowlist(name, body.values, allow_all=body.allow_all)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/mcp/servers/{name}/{capability}/allowlist")
    async def set_mcp_capability_allowlist(name: str, capability: str, body: McpAllowlistBody):
        try:
            service.set_capability_allowlist(name, capability, body.values)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/mcp/servers/{name}/resources/read")
    async def read_mcp_resource(name: str, body: McpReadBody):
        try:
            value = await service.read_resource(name, body.uri)
            return {"content": value[:100_000], "truncated": len(value) > 100_000}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/mcp/servers/{name}/prompts/render")
    async def render_mcp_prompt(name: str, body: McpPromptBody):
        try:
            value = await service.render_prompt(name, body.prompt, body.arguments)
            return {"content": value[:100_000], "truncated": len(value) > 100_000}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/mcp/servers/{name}/enabled")
    async def set_mcp_enabled(name: str, body: McpEnabledBody):
        try:
            service.enable(name, body.enabled)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/mcp/servers/{name}/test")
    async def test_mcp(name: str):
        try:
            return await service.test(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/mcp/servers/{name}/reconnect")
    async def reconnect_mcp(name: str):
        try:
            service.request_reconnect(name)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/api/mcp/servers/{name}")
    async def remove_mcp(name: str):
        try:
            service.remove(name)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
