"""Character management use cases."""

from dataclasses import dataclass

from sqlalchemy import select
from zhiyu.infrastructure.database.models import Conversation, Memory, MemoryJob, McpServerConfig, CharacterSkill, ModelConfig
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository

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
    default_model_id: str | None

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
        default_model_id=character.default_model_id,
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
        default_model_id: str | None = None,
    ) -> CharacterSummary:
        name = name.strip()
        if not name:
            raise ValueError("智能体名称不能为空")
        with self.session_factory() as db:
            self._validate_model(db, default_model_id)
            character = self.characters.create(
                db,
                name=name,
                description=description,
                personality=personality,
                background=background,
                speaking_style=speaking_style,
                system_prompt=system_prompt,
                default_model_id=default_model_id,
            )
            IdentityRepository().for_agent(db, character.id)
            return _summary(character)

    @staticmethod
    def _validate_model(db, model_id):
        if model_id is not None and db.get(ModelConfig, model_id) is None:
            raise ValueError("默认模型不存在")

    def update(self, character_id: str, **fields) -> CharacterSummary:
        allowed = {"name", "description", "personality", "background", "speaking_style", "system_prompt", "default_model_id"}
        fields = {key: value for key, value in fields.items() if key in allowed}
        if "name" in fields:
            fields["name"] = (fields["name"] or "").strip()
            if not fields["name"]:
                raise ValueError("智能体名称不能为空")
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None:
                raise ValueError("智能体不存在")
            if "default_model_id" in fields:
                self._validate_model(db, fields["default_model_id"])
            character = self.characters.update(db, character, **fields)
            IdentityRepository().for_agent(db, character.id)
            return _summary(character)

    def delete(self, character_id: str) -> None:
        with self.session_factory() as db:
            for model in (Conversation, Memory, MemoryJob, McpServerConfig):
                if db.scalars(select(model).where(model.character_id == character_id)).first() is not None:
                    raise ValueError("请先删除该智能体的会话、记忆和 MCP 配置")
            for association in db.scalars(select(CharacterSkill).where(CharacterSkill.character_id == character_id)).all():
                db.delete(association)
            db.flush()
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
            if conversation.character_id != character.id and MessageRepository().list_by_conversation(db, conversation.id):
                raise ValueError("已有消息的会话不能更换智能体，请新建会话")
            conversation.identity_id = IdentityRepository().for_agent(db, character.id).id
            conversation.character_id = character.id
            db.commit()
