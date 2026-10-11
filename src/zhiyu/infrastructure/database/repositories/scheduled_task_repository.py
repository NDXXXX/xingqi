"""One-time reminder persistence and atomic delivery claiming."""

from __future__ import annotations

from datetime import timedelta

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import ScheduledTask, utcnow


class ScheduledTaskRepository:
    def create(self, db: Session, **values) -> ScheduledTask:
        task = ScheduledTask(id=str(uuid4()), **values)
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def get(self, db: Session, task_id: str) -> ScheduledTask | None:
        return db.get(ScheduledTask, task_id)

    def list(self, db: Session) -> list[ScheduledTask]:
        return list(db.scalars(select(ScheduledTask).order_by(ScheduledTask.due_at, ScheduledTask.created_at)))

    def update(self, db: Session, task: ScheduledTask, **values) -> ScheduledTask:
        for name, value in values.items():
            setattr(task, name, value)
        task.updated_at = utcnow()
        db.commit()
        db.refresh(task)
        return task

    def delete(self, db: Session, task: ScheduledTask) -> None:
        db.delete(task)
        db.commit()

    def due_local(self, db: Session, now) -> list[ScheduledTask]:
        ids = list(db.scalars(
            select(ScheduledTask.id).where(
                ScheduledTask.channel == "local",
                ScheduledTask.status == "pending",
                ScheduledTask.enabled.is_(True),
                ScheduledTask.due_at <= now,
            )
        ))
        for task_id in ids:
            db.execute(
                update(ScheduledTask)
                .where(ScheduledTask.id == task_id, ScheduledTask.status == "pending")
                .values(status="due", enabled=False, sent_at=now, updated_at=now)
            )
        db.commit()
        return list(db.scalars(select(ScheduledTask).where(ScheduledTask.id.in_(ids)))) if ids else []

    def claim_due_qq(self, db: Session, now) -> list[str]:
        # Recover leases left behind by a stopped process. Delivery is at-least-once
        # if the process exits after QQ accepts a message but before we persist it.
        db.execute(
            update(ScheduledTask)
            .where(
                ScheduledTask.channel == "qq",
                ScheduledTask.status == "sending",
                ScheduledTask.updated_at <= now - timedelta(minutes=2),
            )
            .values(status="pending", next_attempt_at=now, updated_at=now)
        )
        ids = list(db.scalars(
            select(ScheduledTask.id).where(
                ScheduledTask.channel == "qq",
                ScheduledTask.status == "pending",
                ScheduledTask.enabled.is_(True),
                ScheduledTask.due_at <= now,
                ScheduledTask.next_attempt_at <= now,
            ).order_by(ScheduledTask.due_at).limit(20)
        ))
        claimed = []
        for task_id in ids:
            result = db.execute(
                update(ScheduledTask)
                .where(
                    ScheduledTask.id == task_id,
                    ScheduledTask.status == "pending",
                    ScheduledTask.enabled.is_(True),
                    ScheduledTask.next_attempt_at <= now,
                )
                .values(status="sending", attempts=ScheduledTask.attempts + 1, updated_at=now)
            )
            if result.rowcount == 1:
                claimed.append(task_id)
        db.commit()
        return claimed
