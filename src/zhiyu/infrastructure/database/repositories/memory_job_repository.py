"""持久化记忆提取任务。"""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import MemoryJob, utcnow


class MemoryJobRepository:
    def create(
        self,
        db: Session,
        *,
        user_message_id: str,
        assistant_message_id: str | None,
        identity_id: str,
        provider_id: str,
        model: str,
    ) -> MemoryJob:
        existing = self.get_by_user_message(db, user_message_id)
        if existing is not None:
            return existing
        job = MemoryJob(
            id=str(uuid4()),
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            identity_id=identity_id,
            provider_id=provider_id,
            model=model,
            status="pending",
            attempts=0,
        )
        db.add(job)
        db.flush()
        return job

    def get(self, db: Session, job_id: str) -> MemoryJob | None:
        return db.get(MemoryJob, job_id)

    def get_by_user_message(self, db: Session, user_message_id: str) -> MemoryJob | None:
        return db.scalars(
            select(MemoryJob).where(MemoryJob.user_message_id == user_message_id)
        ).first()

    def list_by_status(self, db: Session, status: str) -> list[MemoryJob]:
        return list(
            db.scalars(
                select(MemoryJob)
                .where(MemoryJob.status == status)
                .order_by(MemoryJob.created_at)
            )
        )

    def claim(self, db: Session, job_id: str) -> MemoryJob | None:
        result = db.execute(
            update(MemoryJob)
            .where(MemoryJob.id == job_id, MemoryJob.status == "pending")
            .values(
                status="processing",
                attempts=MemoryJob.attempts + 1,
                last_error=None,
                updated_at=utcnow(),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return self.get(db, job_id)

    def finish(self, db: Session, job: MemoryJob, status: str, error: str | None = None) -> None:
        job.status = status
        job.last_error = error
        job.updated_at = utcnow()
        db.commit()

    def release(self, db: Session, job_id: str) -> None:
        db.execute(
            update(MemoryJob)
            .where(MemoryJob.id == job_id, MemoryJob.status == "processing")
            .values(status="pending", updated_at=utcnow())
        )
        db.commit()

    def recover_interrupted(self, db: Session, *, stale_after_seconds: int = 300) -> int:
        cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
        result = db.execute(
            update(MemoryJob)
            .where(MemoryJob.status == "processing", MemoryJob.updated_at <= cutoff)
            .values(status="pending", updated_at=utcnow())
        )
        db.commit()
        return result.rowcount

    def retry_failed(self, db: Session) -> int:
        result = db.execute(
            update(MemoryJob)
            .where(MemoryJob.status == "failed")
            .values(status="pending", attempts=0, last_error=None, updated_at=utcnow())
        )
        db.commit()
        return result.rowcount

    def cancel_pending(self, db: Session, identity_id: str) -> int:
        result = db.execute(
            update(MemoryJob)
            .where(
                MemoryJob.identity_id == identity_id,
                MemoryJob.status.in_(("pending", "processing")),
            )
            .values(status="cancelled", updated_at=utcnow())
        )
        db.commit()
        return result.rowcount

    def counts(self, db: Session) -> dict[str, int]:
        rows = db.execute(
            select(MemoryJob.status, func.count()).group_by(MemoryJob.status)
        ).all()
        return {status: count for status, count in rows}
