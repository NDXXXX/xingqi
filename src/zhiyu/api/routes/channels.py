"""QQ and channel event management endpoints."""

from fastapi import APIRouter, HTTPException, Query

from zhiyu.api.schemas.channels import DeliveryRetryBody, QQConfigureBody, QQGroupBody
from zhiyu.application.runtime import RuntimeHost


def build_channels_router(runtime: RuntimeHost) -> APIRouter:
    router = APIRouter()
    service = runtime.channel_service

    @router.get("/api/qq/config")
    async def get_qq_config():
        return service.configured_qq()

    @router.put("/api/qq/config")
    async def configure_qq(body: QQConfigureBody):
        try:
            service.configure_qq(
                body.endpoint,
                token=body.token or None,
                owner_user_id=body.owner_user_id or None,
            )
            return service.configured_qq()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/qq/start")
    async def start_qq():
        try:
            return {"endpoint": await service.start_qq()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/qq/stop")
    async def stop_qq():
        await runtime.channel_manager.disconnect("qq")
        return {"ok": True}

    @router.put("/api/qq/groups/{group_id}")
    async def set_qq_group(group_id: str, body: QQGroupBody):
        try:
            return service.set_group_policy(
                group_id,
                enabled=body.enabled,
                require_mention=body.require_mention,
                tool_allowlist=body.tool_allowlist,
                system_prompt=body.system_prompt,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/channel-events/{event_id}/replay")
    async def replay_event(event_id: str):
        try:
            service.replay_event(event_id)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/channel-deliveries/{delivery_id}/retry")
    async def retry_delivery(delivery_id: str, body: DeliveryRetryBody):
        try:
            return {"event_id": service.retry_delivery(
                delivery_id, allow_unknown=body.allow_unknown
            )}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/channels")
    async def list_channels():
        return runtime.channel_manager.list()

    @router.get("/api/channel-events")
    async def list_channel_events(limit: int = Query(default=50, ge=1, le=200)):
        return service.list_events(limit)

    @router.get("/api/qq/groups")
    async def list_qq_groups():
        return service.list_group_policies()

    @router.get("/api/channel-deliveries")
    async def list_channel_deliveries(limit: int = Query(default=50, ge=1, le=200)):
        return service.list_deliveries(limit)

    return router
