"""跨渠道身份仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Identity

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
            id=LOCAL_IDENTITY_ID if channel == "local" else str(uuid4()),
            channel=channel,
            external_user_id=external_user_id,
            display_name=display_name,
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)
        return identity

    def local(self, db: Session) -> Identity:
        return self.get_or_create(db, "local", "local-user", "Local User")
