"""Character 仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Character, utcnow


class CharacterRepository:
    def list(self, db: Session) -> list[Character]:
        return list(db.scalars(select(Character).order_by(Character.name)))

    def get(self, db: Session, character_id: str) -> Character | None:
        return db.get(Character, character_id)

    def create(
        self,
        db: Session,
        *,
        name: str,
        avatar: str | None = None,
        description: str | None = None,
        personality: str | None = None,
        background: str | None = None,
        speaking_style: str | None = None,
        system_prompt: str | None = None,
        default_model_id: str | None = None,
    ) -> Character:
        character = Character(
            id=str(uuid4()),
            name=name,
            avatar=avatar,
            description=description,
            personality=personality,
            background=background,
            speaking_style=speaking_style,
            system_prompt=system_prompt,
            default_model_id=default_model_id,
        )
        db.add(character)
        db.commit()
        db.refresh(character)
        return character

    def update(self, db: Session, character: Character, **fields) -> Character:
        for key, value in fields.items():
            if hasattr(character, key):
                setattr(character, key, value)
        character.updated_at = utcnow()
        db.commit()
        db.refresh(character)
        return character

    def delete(self, db: Session, character_id: str) -> bool:
        character = self.get(db, character_id)
        if character is None:
            return False
        db.delete(character)
        db.commit()
        return True
