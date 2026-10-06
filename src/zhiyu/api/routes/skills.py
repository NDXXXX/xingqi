"""Skill lifecycle endpoints."""

from fastapi import APIRouter, HTTPException

from zhiyu.api.schemas.integrations import McpEnabledBody, SkillInstallBody, SkillUpdateBody
from zhiyu.application.runtime import RuntimeHost
from zhiyu.application.skills import SkillService
from zhiyu.core.tools.registry import default_registry


def build_skills_router(runtime: RuntimeHost, skills: SkillService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/skills")
    async def list_skills():
        tools = {tool.name for tool in runtime.mcp_manager.tools()}
        tools.update(default_registry().names())
        return skills.list(tools)

    @router.post("/api/skills/install")
    async def install_skill(body: SkillInstallBody):
        try:
            return skills.install(body.source, ref=body.ref, subdir=body.subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/skills/preview")
    async def preview_skill(body: SkillInstallBody):
        try:
            return skills.preview(body.source, ref=body.ref, subdir=body.subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/skills/trash")
    async def list_skill_trash():
        return skills.trash_list()

    @router.post("/api/skills/{name}/update-preview")
    async def preview_skill_update(name: str, body: SkillUpdateBody):
        try:
            return skills.update(name, ref=body.ref, apply=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/skills/{name}/update")
    async def update_skill(name: str, body: SkillUpdateBody):
        try:
            result = skills.update(name, ref=body.ref, apply=True)
            skills.request_reload()
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/skills/{name}/enabled")
    async def set_skill_enabled(name: str, body: McpEnabledBody):
        try:
            skills.enable(name, body.enabled)
            skills.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/api/skills/{name}")
    async def remove_skill(name: str):
        try:
            skills.remove(name)
            skills.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/skills/{name}/restore")
    async def restore_skill(name: str):
        try:
            skills.restore(name)
            skills.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
