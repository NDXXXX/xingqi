"""Skill lifecycle endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from zhiyu.application.characters import CharacterService

from zhiyu.api.schemas.integrations import McpEnabledBody, SkillInstallBody, SkillUpdateBody
from zhiyu.application.runtime import RuntimeHost
from zhiyu.application.skills import SkillService
from zhiyu.core.tools.registry import default_registry


def build_skills_router(runtime: RuntimeHost, skills: SkillService) -> APIRouter:
    router = APIRouter()

    def scoped(character_id: str | None = None):
        if character_id is not None and CharacterService(skills.session_factory).get(character_id) is None:
            raise HTTPException(404, "智能体不存在")
        return SkillService(skills.session_factory, skills.skills_dir, character_id)

    @router.get("/api/skills")
    async def list_skills(service: SkillService = Depends(scoped)):
        tools = {tool.name for tool in runtime.mcp_manager.tools(service.character_id)}
        tools.update(default_registry().names())
        return service.list(tools)

    @router.post("/api/skills/install")
    async def install_skill(body: SkillInstallBody, service: SkillService = Depends(scoped)):
        try:
            return service.install(body.source, ref=body.ref, subdir=body.subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/skills/preview")
    async def preview_skill(body: SkillInstallBody, service: SkillService = Depends(scoped)):
        try:
            return service.preview(body.source, ref=body.ref, subdir=body.subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/skills/trash")
    async def list_skill_trash(service: SkillService = Depends(scoped)):
        return service.trash_list()

    @router.post("/api/skills/{name}/update-preview")
    async def preview_skill_update(name: str, body: SkillUpdateBody, service: SkillService = Depends(scoped)):
        try:
            return service.update(name, ref=body.ref, apply=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/skills/{name}/update")
    async def update_skill(name: str, body: SkillUpdateBody, service: SkillService = Depends(scoped)):
        try:
            result = service.update(name, ref=body.ref, apply=True)
            service.request_reload()
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/skills/{name}/enabled")
    async def set_skill_enabled(name: str, body: McpEnabledBody, service: SkillService = Depends(scoped)):
        try:
            service.enable(name, body.enabled)
            service.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/api/skills/{name}")
    async def remove_skill(name: str, service: SkillService = Depends(scoped)):
        try:
            service.remove(name)
            service.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/skills/{name}/restore")
    async def restore_skill(name: str, service: SkillService = Depends(scoped)):
        try:
            service.restore(name)
            service.request_reload()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
