"""Agent Run 与步骤记录仓储。"""

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import AgentRun, AgentRunStep, utcnow


class AgentRunRepository:
    def create(
        self,
        db: Session,
        conversation_id: str,
        provider_id: str,
        model_id: str,
        *,
        channel_event_id: str | None = None,
    ) -> AgentRun:
        if channel_event_id:
            existing = self.get_by_event(db, channel_event_id)
            if existing is not None:
                existing.status = "running"
                existing.error = None
                existing.finished_at = None
                db.commit()
                db.refresh(existing)
                return existing
        run = AgentRun(
            id=str(uuid4()),
            conversation_id=conversation_id,
            provider_id=provider_id,
            model_id=model_id,
            channel_event_id=channel_event_id,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def get_by_event(self, db: Session, channel_event_id: str) -> AgentRun | None:
        return db.scalars(
            select(AgentRun)
            .options(selectinload(AgentRun.steps))
            .where(AgentRun.channel_event_id == channel_event_id)
        ).first()

    def get(self, db: Session, run_id: str) -> AgentRun | None:
        return db.scalars(
            select(AgentRun).options(selectinload(AgentRun.steps)).where(AgentRun.id == run_id)
        ).first()

    def list_for_conversation(self, db: Session, conversation_id: str) -> list[AgentRun]:
        return list(
            db.scalars(
                select(AgentRun)
                .options(selectinload(AgentRun.steps))
                .where(AgentRun.conversation_id == conversation_id)
                .order_by(AgentRun.started_at.desc())
            )
        )

    def add_event(self, db: Session, run_id: str, event: dict) -> AgentRunStep | None:
        event_type = event.get("type")
        if event_type not in {"step", "tool"}:
            return None
        step = AgentRunStep(
            id=str(uuid4()),
            run_id=run_id,
            step_type=event_type,
            name=event.get("name", event_type),
            status=event.get("status", "completed"),
            input_json=self._json(event.get("input")),
            output_json=self._json(event.get("output")),
            finished_at=utcnow(),
            error=event.get("error"),
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        return step

    def finish(
        self,
        db: Session,
        run_id: str,
        status: str,
        error: str | None = None,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        response_message_id: str | None = None,
    ) -> None:
        run = db.get(AgentRun, run_id)
        if run is None:
            return
        finished_at = utcnow()
        run.status = status
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - run.started_at).total_seconds() * 1000)
        run.error = error
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        if provider_id is not None:
            run.provider_id = provider_id
        if model_id is not None:
            run.model_id = model_id
        if response_message_id is not None:
            run.response_message_id = response_message_id
        db.commit()

    @staticmethod
    def _json(value) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)
