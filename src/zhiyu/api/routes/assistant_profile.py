"""个人助手设定接口。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from zhiyu.application.assistant_profile import AssistantProfileService


class ProfileFileBody(BaseModel):
    content: str = Field(max_length=20000)


def build_assistant_profile_router(service: AssistantProfileService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/assistant-profile")
    async def get_assistant_profile():
        return service.get()

    @router.put("/api/assistant-profile/{name}")
    async def update_assistant_profile(name: str, body: ProfileFileBody):
        try:
            return service.update(name, body.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/assistant-profile/bootstrap/complete")
    async def complete_bootstrap():
        return service.complete_bootstrap()

    return router
