"""Character management use cases."""

from dataclasses import dataclass

from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.character_repository import CharacterRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


@dataclass(slots=True)
class CharacterSummary:
    id: str
    name: str
    description: str | None
    personality: str | None
    background: str | None
    speaking_style: str | None
    system_prompt: str | None

    @property
    def has_system_prompt(self) -> bool:
        return bool(self.system_prompt and self.system_prompt.strip())


def _summary(character) -> CharacterSummary:
    return CharacterSummary(
        id=character.id,
        name=character.name,
        description=character.description,
        personality=character.personality,
        background=character.background,
        speaking_style=character.speaking_style,
        system_prompt=character.system_prompt,
    )


class CharacterService:
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory
        self.characters = CharacterRepository()
        self.conversations = ConversationRepository()

    def list(self) -> list[CharacterSummary]:
        with self.session_factory() as db:
            return [_summary(item) for item in self.characters.list(db)]

    def get(self, character_id: str) -> CharacterSummary | None:
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            return _summary(character) if character is not None else None

    def create(
        self,
        *,
        name: str,
        description: str | None = None,
        personality: str | None = None,
        background: str | None = None,
        speaking_style: str | None = None,
        system_prompt: str | None = None,
    ) -> CharacterSummary:
        with self.session_factory() as db:
            character = self.characters.create(
                db,
                name=name,
                description=description,
                personality=personality,
                background=background,
                speaking_style=speaking_style,
                system_prompt=system_prompt,
            )
            return _summary(character)

    def delete(self, character_id: str) -> None:
        with self.session_factory() as db:
            if not self.characters.delete(db, character_id):
                raise ValueError("角色不存在")

    def current_for_conversation(self, conversation_id: str) -> CharacterSummary | None:
        with self.session_factory() as db:
            conversation = self.conversations.get(db, conversation_id)
            if conversation is None or conversation.character_id is None:
                return None
            character = self.characters.get(db, conversation.character_id)
            return _summary(character) if character is not None else None

    def assign_to_conversation(self, conversation_id: str, character_id: str) -> None:
        with self.session_factory() as db:
            conversation = self.conversations.get(db, conversation_id)
            character = self.characters.get(db, character_id)
            if conversation is None or character is None:
                raise ValueError("会话或角色不存在")
            conversation.character_id = character.id
            db.commit()
