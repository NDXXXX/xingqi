"""User-managed one-time reminders."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from zhiyu.scheduled_tasks.service import ScheduledTaskService


class ScheduledTaskBody(BaseModel):
    content: str
    due_at: datetime
    timezone: str
    channel: str = "local"


class EnabledBody(BaseModel):
    enabled: bool


def build_scheduled_tasks_router(service: ScheduledTaskService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/scheduled-tasks")
    async def list_tasks():
        return service.list()

    @router.post("/api/scheduled-tasks")
    async def create_task(body: ScheduledTaskBody):
        try:
            return service.create(content=body.content, due_at=body.due_at, timezone_name=body.timezone, channel=body.channel)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/api/scheduled-tasks/{task_id}")
    async def update_task(task_id: str, body: ScheduledTaskBody):
        try:
            return service.update(task_id, content=body.content, due_at=body.due_at, timezone_name=body.timezone, channel=body.channel)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/api/scheduled-tasks/{task_id}/enabled")
    async def set_enabled(task_id: str, body: EnabledBody):
        try:
            return service.set_enabled(task_id, body.enabled)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/scheduled-tasks/{task_id}/retry")
    async def retry_task(task_id: str):
        try:
            return service.retry(task_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/scheduled-tasks/{task_id}/complete", status_code=204)
    async def complete_task(task_id: str):
        try:
            service.complete(task_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return None

    @router.delete("/api/scheduled-tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str):
        try:
            service.delete(task_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return None

    return router
