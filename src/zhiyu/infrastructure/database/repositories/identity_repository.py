"""跨渠道身份仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Character, Identity, utcnow

LOCAL_IDENTITY_ID = "00000000-0000-0000-0000-000000000001"


class IdentityRepository:
    def get(self, db: Session, identity_id: str) -> Identity | None:
        return db.get(Identity, identity_id)

    def get_or_create(
        self,
        db: Session,
        channel: str,
        external_user_id: str,
        display_name: str | None = None,
    ) -> Identity:
        identity = db.scalars(
            select(Identity).where(
                Identity.channel == channel,
                Identity.external_user_id == external_user_id,
            )
        ).first()
        if identity is not None:
            if display_name and identity.display_name != display_name:
                identity.display_name = display_name
                db.commit()
                db.refresh(identity)
            return identity
        identity = Identity(
            id=LOCAL_IDENTITY_ID if channel == "local" else external_user_id if channel == "agent" else str(uuid4()),
            channel=channel,
            external_user_id=external_user_id,
            display_name=display_name,
            memory_reset_at=utcnow() if channel == "agent" else None,
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)
        return identity

    def for_agent(self, db: Session, character_id: str | None) -> Identity:
        if character_id is None:
            return self.local(db)
        character = db.get(Character, character_id)
        if character is None:
            raise ValueError("智能体不存在")
        return self.get_or_create(db, "agent", character.id, character.name)

    def local(self, db: Session) -> Identity:
        return self.get_or_create(db, "local", "local-user", "Local User")
