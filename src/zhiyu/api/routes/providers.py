"""Provider management endpoints."""

from dataclasses import asdict
from fastapi import APIRouter, HTTPException

from zhiyu.application.providers import ProviderService
from zhiyu.api.schemas.providers import (
    ModelBody,
    ModelUpdateBody,
    ProviderCreateBody,
    ProviderDefaultBody,
    ProviderFallbackBody,
    ProviderTestBody,
    ProviderUpdateBody,
)


def build_provider_router(providers: ProviderService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/providers")
    async def list_providers():
        return [asdict(item) for item in providers.list()]

    @router.get("/api/providers/default")
    async def get_default_provider():
        return providers.default_model()

    @router.post("/api/providers")
    async def create_provider(body: ProviderCreateBody):
        try:
            return asdict(providers.add(**body.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/providers/{name}")
    async def get_provider(name: str):
        try:
            return providers.detail(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/api/providers/{name}")
    async def update_provider(name: str, body: ProviderUpdateBody):
        try:
            providers.update(name, **body.model_dump())
            return providers.detail(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/providers/{name}")
    async def delete_provider(name: str):
        try:
            providers.remove(name)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/api/providers/{name}/fallbacks")
    async def set_provider_fallbacks(name: str, body: ProviderFallbackBody):
        try:
            providers.set_fallbacks(name, body.providers)
            return {"providers": providers.fallbacks(name)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/providers/{name}/models")
    async def add_provider_model(name: str, body: ModelBody):
        try:
            return providers.add_model(name, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/providers/{name}/models/{model_id}")
    async def update_provider_model(name: str, model_id: str, body: ModelUpdateBody):
        try:
            return providers.update_model(name, model_id, **body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/api/providers/{name}/models/{model_id}")
    async def delete_provider_model(name: str, model_id: str):
        try:
            providers.remove_model(name, model_id)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/providers/{name}/test")
    async def test_provider(name: str, body: ProviderTestBody):
        try:
            return {"response": await providers.test(name, body.model)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/providers/default")
    async def set_default_provider(body: ProviderDefaultBody):
        try:
            providers.set_default(body.provider, body.model)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
