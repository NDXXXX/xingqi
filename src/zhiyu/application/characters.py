"""Character management use cases."""

from dataclasses import dataclass
import base64
import binascii
import json
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, or_, select
from zhiyu.infrastructure.config.settings import settings
from zhiyu.core.agent.run_manager import active_runs
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.config.keystore import KeyStore, keystore
from zhiyu.infrastructure.database.models import (
    AgentRun,
    AgentRunStep,
    Character,
    CharacterSkill,
    Conversation,
    ConversationSummary,
    ForgottenConversation,
    Identity,
    Memory,
    MemoryConsolidationRun,
    MemoryEmbedding,
    MemoryFileIndex,
    MemoryJob,
    MemoryMutation,
    MemoryRecallEvent,
    MemorySource,
    Message,
    McpRuntimeState,
    McpServerConfig,
    ModelConfig,
    Provider,
)
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository

from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.character_repository import CharacterRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CharacterSummary:
    id: str
    name: str
    avatar: str | None
    description: str | None
    personality: str | None
    background: str | None
    speaking_style: str | None
    system_prompt: str | None
    opening_message: str | None
    world_setting: str | None
    initial_scene: str | None
    behavior_preferences: str | None
    default_model_id: str | None

    @property
    def has_system_prompt(self) -> bool:
        return bool(self.system_prompt and self.system_prompt.strip())


def _summary(character) -> CharacterSummary:
    return CharacterSummary(
        id=character.id,
        name=character.name,
        avatar=character.avatar,
        description=character.description,
        personality=character.personality,
        background=character.background,
        speaking_style=character.speaking_style,
        system_prompt=character.system_prompt,
        opening_message=character.opening_message,
        world_setting=character.world_setting,
        initial_scene=character.initial_scene,
        behavior_preferences=character.behavior_preferences,
        default_model_id=character.default_model_id,
    )


class CharacterService:
    def __init__(
        self,
        session_factory=SessionLocal,
        avatar_dir: Path | None = None,
        memory_store: MemoryStore | None = None,
        secrets: KeyStore = keystore,
    ) -> None:
        self.session_factory = session_factory
        self.avatar_dir = avatar_dir or settings.data_dir / "avatars"
        self.memory_store = memory_store or MemoryStore()
        self.secrets = secrets
        self.characters = CharacterRepository()
        self.conversations = ConversationRepository()

    def list(self) -> list[CharacterSummary]:
        with self.session_factory() as db:
            return [_summary(item) for item in self.characters.list(db)]

    def get(self, character_id: str) -> CharacterSummary | None:
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            return _summary(character) if character is not None else None

    def export_template(self, character_id: str) -> dict:
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None:
                raise ValueError("智能体不存在")
            default_model = None
            model = db.get(ModelConfig, character.default_model_id) if character.default_model_id else None
            if model is not None:
                provider = db.get(Provider, model.provider_id)
                if provider is not None:
                    default_model = {"provider": provider.name, "model": model.model_name}
            result = {
                "format": "xingqi-character-template",
                "version": 1,
                "character": {
                    key: getattr(character, key)
                    for key in (
                        "name", "description", "personality", "background", "speaking_style",
                        "system_prompt", "opening_message", "world_setting", "initial_scene",
                        "behavior_preferences",
                    )
                },
                "default_model": default_model,
                "avatar": None,
            }
        avatar_path = self.avatar_path(character_id)
        if avatar_path is not None:
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(avatar_path.suffix)
            if mime:
                result["avatar"] = {
                    "mime_type": mime,
                    "data": base64.b64encode(avatar_path.read_bytes()).decode("ascii"),
                }
        return result

    def import_template(self, payload: dict) -> tuple[CharacterSummary, str | None]:
        if not isinstance(payload, dict) or set(payload) != {"format", "version", "character", "default_model", "avatar"}:
            raise ValueError("角色模板字段不符合格式")
        if payload["format"] != "xingqi-character-template" or type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError("不支持的角色模板版本")
        fields = {
            "name", "description", "personality", "background", "speaking_style",
            "system_prompt", "opening_message", "world_setting", "initial_scene",
            "behavior_preferences",
        }
        character = payload["character"]
        if not isinstance(character, dict) or set(character) != fields:
            raise ValueError("角色设定字段不符合模板格式")
        if not isinstance(character["name"], str) or not character["name"].strip() or len(character["name"]) > 255:
            raise ValueError("角色名称不能为空且不能超过 255 个字符")
        for key, value in character.items():
            if key == "name":
                continue
            if value is not None and (not isinstance(value, str) or len(value) > 20_000):
                raise ValueError(f"角色字段 {key} 必须是 20000 字以内的文本")
        avatar = payload["avatar"]
        image: tuple[str, bytes] | None = None
        if avatar is not None:
            if (
                not isinstance(avatar, dict)
                or set(avatar) != {"mime_type", "data"}
                or not isinstance(avatar["mime_type"], str)
                or not isinstance(avatar["data"], str)
            ):
                raise ValueError("头像数据格式无效")
            try:
                content = base64.b64decode(avatar["data"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("头像编码无效") from exc
            image = (avatar["mime_type"], content)
            self._validate_avatar(*image)
        model_key = payload["default_model"]
        model_id, warning = None, None
        if model_key is not None:
            if (
                not isinstance(model_key, dict)
                or set(model_key) != {"provider", "model"}
                or not all(isinstance(model_key[k], str) and len(model_key[k]) <= 255 for k in model_key)
            ):
                raise ValueError("默认模型信息格式无效")
            with self.session_factory() as db:
                matches = list(db.scalars(
                    select(ModelConfig).join(Provider).where(
                        Provider.name == model_key["provider"],
                        ModelConfig.model_name == model_key["model"],
                        Provider.enabled.is_(True),
                        ModelConfig.enabled.is_(True),
                        or_(Provider.api_key_ref.is_not(None), Provider.base_url.is_not(None)),
                    )
                ))
                if len(matches) == 1:
                    model_id = matches[0].id
                else:
                    warning = "未找到唯一匹配的本机默认模型；角色已导入，请在角色设置中选择模型。"
        created = self.create(**character, default_model_id=model_id)
        if image is not None:
            try:
                created = self.upload_avatar(created.id, *image)
            except Exception:
                self.delete(created.id)
                raise
        return created, warning

    def create(
        self,
        *,
        name: str,
        description: str | None = None,
        personality: str | None = None,
        background: str | None = None,
        speaking_style: str | None = None,
        system_prompt: str | None = None,
        opening_message: str | None = None,
        world_setting: str | None = None,
        initial_scene: str | None = None,
        behavior_preferences: str | None = None,
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
                opening_message=opening_message,
                world_setting=world_setting,
                initial_scene=initial_scene,
                behavior_preferences=behavior_preferences,
                default_model_id=default_model_id,
            )
            IdentityRepository().for_agent(db, character.id)
            return _summary(character)

    @staticmethod
    def _validate_model(db, model_id):
        if model_id is not None and db.get(ModelConfig, model_id) is None:
            raise ValueError("默认模型不存在")

    def update(self, character_id: str, **fields) -> CharacterSummary:
        allowed = {
            "name", "description", "personality", "background", "speaking_style",
            "system_prompt", "opening_message", "world_setting", "initial_scene",
            "behavior_preferences", "default_model_id",
        }
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

    def upload_avatar(self, character_id: str, content_type: str, content: bytes) -> CharacterSummary:
        self._validate_avatar(content_type, content)
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[content_type]
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None:
                raise ValueError("智能体不存在")
            old_avatar = character.avatar
            filename = f"{uuid4().hex}{extension}"
            self.avatar_dir.mkdir(parents=True, exist_ok=True)
            destination = self.avatar_dir / filename
            temporary = self.avatar_dir / f".{filename}.tmp"
            temporary.write_bytes(content)
            temporary.replace(destination)
            character.avatar = filename
            try:
                db.commit()
                db.refresh(character)
                result = _summary(character)
            except Exception:
                db.rollback()
                destination.unlink(missing_ok=True)
                raise
        self._remove_avatar_file(old_avatar)
        return result

    @staticmethod
    def _validate_avatar(content_type: str, content: bytes) -> None:
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("头像不能超过 2 MiB")
        formats = {
            "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
            "image/webp": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }
        check = formats.get(content_type)
        if check is None or not check(content):
            raise ValueError("头像仅支持有效的 PNG、JPEG 或 WebP 图片")

    def clear_avatar(self, character_id: str) -> CharacterSummary:
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None:
                raise ValueError("智能体不存在")
            old_avatar = character.avatar
            character.avatar = None
            db.commit()
            db.refresh(character)
            result = _summary(character)
        self._remove_avatar_file(old_avatar)
        return result

    def avatar_path(self, character_id: str) -> Path | None:
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None or not character.avatar:
                return None
            filename = Path(character.avatar).name
            path = self.avatar_dir / filename
            return path if path.is_file() and not path.is_symlink() else None

    def _remove_avatar_file(self, filename: str | None) -> None:
        if not filename or Path(filename).name != filename:
            return
        path = self.avatar_dir / filename
        if path.is_file():
            path.unlink()

    def delete(self, character_id: str) -> None:
        self.recover_deletions(self.session_factory, self.memory_store, self.avatar_dir)
        with self.session_factory() as db:
            character = self.characters.get(db, character_id)
            if character is None:
                raise ValueError("角色不存在")
            identity = db.scalars(
                select(Identity).where(
                    Identity.channel == "agent",
                    Identity.external_user_id == character_id,
                )
            ).first()
            identity_id = identity.id if identity else None
            conversation_ids = list(db.scalars(
                select(Conversation.id).where(Conversation.character_id == character_id)
            ))
            avatar = character.avatar
        for conversation_id in conversation_ids:
            active_runs.cancel_conversation(conversation_id)
        quarantined = self.memory_store.quarantine_identity(character_id)
        secret_refs: set[str] = set()
        with self.session_factory() as db:
            try:
                identity = db.scalars(
                    select(Identity).where(
                        Identity.channel == "agent",
                        Identity.external_user_id == character_id,
                    )
                ).first()
                identity_id = identity.id if identity else identity_id
                conversation_ids = list(db.scalars(
                    select(Conversation.id).where(Conversation.character_id == character_id)
                ))
                run_ids = list(db.scalars(
                    select(AgentRun.id).where(AgentRun.conversation_id.in_(conversation_ids))
                )) if conversation_ids else []
                mcp_configs = list(db.scalars(
                    select(McpServerConfig).where(McpServerConfig.character_id == character_id)
                ))
                for config in mcp_configs:
                    try:
                        secret_refs.update(json.loads(config.secret_refs_json or "{}").values())
                    except (TypeError, ValueError):
                        pass
                    db.execute(delete(McpRuntimeState).where(McpRuntimeState.server_config_id == config.id))
                    db.delete(config)
                if run_ids:
                    db.execute(delete(AgentRunStep).where(AgentRunStep.run_id.in_(run_ids)))
                    db.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
                if conversation_ids:
                    message_ids = list(db.scalars(select(Message.id).where(Message.conversation_id.in_(conversation_ids))))
                    if message_ids:
                        db.execute(delete(MemoryJob).where(
                            (MemoryJob.user_message_id.in_(message_ids))
                            | (MemoryJob.assistant_message_id.in_(message_ids))
                        ))
                    db.execute(delete(ConversationSummary).where(ConversationSummary.conversation_id.in_(conversation_ids)))
                    db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
                    db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
                if identity_id:
                    db.execute(delete(MemoryJob).where(
                        (MemoryJob.identity_id == identity_id) | (MemoryJob.character_id == character_id)
                    ))
                    memory_ids = list(db.scalars(select(Memory.id).where(
                        (Memory.identity_id == identity_id) | (Memory.character_id == character_id)
                    )))
                    if memory_ids:
                        db.execute(delete(MemorySource).where(MemorySource.memory_id.in_(memory_ids)))
                        db.execute(delete(MemoryRecallEvent).where(MemoryRecallEvent.memory_id.in_(memory_ids)))
                        db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(memory_ids)))
                    db.execute(delete(MemorySource).where(MemorySource.identity_id == identity_id))
                    db.execute(delete(MemoryRecallEvent).where(MemoryRecallEvent.identity_id == identity_id))
                    db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.character_id == character_id))
                    db.execute(delete(Memory).where(
                        (Memory.identity_id == identity_id) | (Memory.character_id == character_id)
                    ))
                    db.execute(delete(MemoryFileIndex).where(MemoryFileIndex.identity_id == identity_id))
                    db.execute(delete(MemoryMutation).where(MemoryMutation.identity_id == identity_id))
                    db.execute(delete(MemoryConsolidationRun).where(MemoryConsolidationRun.identity_id == identity_id))
                    db.execute(delete(ForgottenConversation).where(ForgottenConversation.identity_id == identity_id))
                    db.delete(identity)
                else:
                    db.execute(delete(MemoryJob).where(MemoryJob.character_id == character_id))
                    memory_ids = list(db.scalars(
                        select(Memory.id).where(Memory.character_id == character_id)
                    ))
                    if memory_ids:
                        db.execute(delete(MemorySource).where(MemorySource.memory_id.in_(memory_ids)))
                        db.execute(delete(MemoryRecallEvent).where(MemoryRecallEvent.memory_id.in_(memory_ids)))
                        db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(memory_ids)))
                    db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.character_id == character_id))
                    db.execute(delete(Memory).where(Memory.character_id == character_id))
                db.execute(delete(CharacterSkill).where(CharacterSkill.character_id == character_id))
                character = self.characters.get(db, character_id)
                if character is None:
                    raise ValueError("角色不存在")
                db.delete(character)
                db.commit()
            except Exception:
                db.rollback()
                if quarantined:
                    self.memory_store.restore_quarantined_identity(character_id)
                raise
        try:
            self.memory_store.remove_quarantined_identity(character_id)
        except OSError:
            logger.warning("角色记忆目录将在下次启动时清理: %s", character_id)
        try:
            self._remove_avatar_file(avatar)
        except OSError:
            logger.warning("角色头像将在下次启动时清理: %s", character_id)
        for ref in secret_refs:
            if not ref:
                continue
            with self.session_factory() as db:
                still_used = False
                for config in db.scalars(select(McpServerConfig)):
                    try:
                        if ref in json.loads(config.secret_refs_json or "{}").values():
                            still_used = True
                            break
                    except (TypeError, ValueError):
                        continue
            if not still_used:
                try:
                    self.secrets.delete(ref)
                except Exception:
                    logger.warning("角色 MCP 凭据未能清理: %s", character_id)
        if mcp_configs:
            from zhiyu.application.mcp import McpService

            with self.session_factory() as db:
                McpService(self.session_factory)._bump_revision(db)

    @staticmethod
    def recover_deletions(
        session_factory,
        memory_store: MemoryStore,
        avatar_dir: Path | None = None,
    ) -> None:
        for character_id in memory_store.quarantined_identities():
            with session_factory() as db:
                exists = db.get(Character, character_id) is not None
            if exists:
                memory_store.restore_quarantined_identity(character_id)
            else:
                memory_store.remove_quarantined_identity(character_id)
        if avatar_dir is not None and avatar_dir.is_dir():
            with session_factory() as db:
                referenced = set(db.scalars(select(Character.avatar).where(Character.avatar.is_not(None))))
            for path in avatar_dir.iterdir():
                if path.is_file() and path.name not in referenced:
                    path.unlink()

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
