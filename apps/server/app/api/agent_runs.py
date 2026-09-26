"""Agent Run 查询与取消 API。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..agent.run_manager import active_runs
from ..database.db import get_db
from ..database.models import AgentRun
from ..database.repositories.agent_run_repository import AgentRunRepository
from ..database.repositories.conversation_repository import ConversationRepository

router = APIRouter(prefix="/api/agent", tags=["agent"])
run_repo = AgentRunRepository()
conversation_repo = ConversationRepository()


class AgentRunStepOut(BaseModel):
    id: str
    step_type: str
    name: str
    status: str
    input_json: str | None
    output_json: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None

    model_config = ConfigDict(from_attributes=True)


class AgentRunOut(BaseModel):
    id: str
    conversation_id: str
    provider_id: str
    model_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None
    steps: list[AgentRunStepOut]

    model_config = ConfigDict(from_attributes=True)


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> AgentRun:
    run = run_repo.get(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return run


@router.get("/conversations/{conversation_id}/runs", response_model=list[AgentRunOut])
def list_runs(conversation_id: str, db: Session = Depends(get_db)) -> list[AgentRun]:
    if conversation_repo.get(db, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return run_repo.list_for_conversation(db, conversation_id)


@router.delete("/runs/{run_id}", status_code=202)
def cancel_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = run_repo.get(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    if run.status != "running":
        raise HTTPException(status_code=409, detail="Agent Run 已结束")
    if not active_runs.cancel(run_id):
        run_repo.finish(db, run_id, "cancelled")
    return {"id": run_id, "status": "cancelling"}
