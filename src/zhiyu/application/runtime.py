"""常驻进程共享的应用生命周期宿主。"""

import asyncio
import logging

from sqlalchemy import select

from zhiyu.application.chat import ChatService
from zhiyu.application.channels import ChannelService
from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.application.standing_intents import StandingIntentService
from zhiyu.application.mcp import CONFIG_REVISION_KEY, McpService
from zhiyu.application.skills import SkillService
from zhiyu.channels.media import MediaStore
from zhiyu.channels.messages import OutboundMessage
from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.router import ChannelRouter
from zhiyu.integrations.mcp.manager import McpManager
from zhiyu.integrations.skills.registry import SkillRegistry, default_registry
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository
from zhiyu.infrastructure.database.models import Identity, MemoryFileIndex, MemoryMutation
from zhiyu.core.memory.indexer import rebuild_index, sync_changed_index
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


logger = logging.getLogger(__name__)


class RuntimeHost:
    def __init__(
        self,
        *,
        chat_service: ChatService | None = None,
        channel_manager: ChannelManager | None = None,
        channel_service: ChannelService | None = None,
        mcp_manager: McpManager | None = None,
        skill_service: SkillService | None = None,
        skill_registry: SkillRegistry = default_registry,
        auto_connect_mcp: bool = True,
        auto_connect_channels: bool = True,
    ) -> None:
        self.chat_service = chat_service or ChatService()
        self.channel_manager = channel_manager or ChannelManager(
            ChannelRouter(self.chat_service),
            self.chat_service.session_factory,
        )
        self.mcp_manager = mcp_manager or self.chat_service.mcp_manager
        self.chat_service.mcp_manager = self.mcp_manager
        self.skill_registry = skill_registry
        self.auto_connect_mcp = auto_connect_mcp
        self.auto_connect_channels = auto_connect_channels and (
            channel_service is not None or isinstance(self.channel_manager, ChannelManager)
        )
        self.mcp_service = McpService(self.chat_service.session_factory)
        self.skill_service = skill_service or SkillService(self.chat_service.session_factory)
        self.settings = SettingRepository()
        if hasattr(self.mcp_manager, "_state_writer"):
            self.mcp_manager._state_writer = self.mcp_service.persist_runtime_state
        self.channel_service = channel_service or ChannelService(
            self.chat_service.session_factory, self.channel_manager
        )
        self.media_store = MediaStore(self.chat_service.session_factory)
        self._recovery_task: asyncio.Task | None = None
        self._integration_task: asyncio.Task | None = None
        self._dream_task: asyncio.Task | None = None
        self._intent_task: asyncio.Task | None = None
        self._integration_revision: int | None = None
        self._skills_revision: int | None = None
        self.channel_start_errors: list[str] = []
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        self.channel_start_errors.clear()
        self.skill_service.register_existing()
        self.skill_registry.reload(self.skill_service.enabled_overrides())
        self.skill_service.purge_expired()
        self._sync_memory_indexes()
        if self.auto_connect_mcp and hasattr(self.mcp_manager, "reconcile"):
            await self._reconcile_integrations()
        if self.auto_connect_channels:
            try:
                await self.channel_service.start_auto_connect()
            except Exception as exc:
                message = str(exc)
                self.channel_start_errors.append(message)
                logger.warning("Channel auto-connect degraded: %s", message)
        self.chat_service.memory_processor.kick()
        self._intent_task = asyncio.create_task(self._reminder_loop())
        self._dream_task = asyncio.create_task(
            ConsolidationProcessor(
                self.chat_service.session_factory,
                getattr(self.chat_service.memory_processor.memory_manager, "store", None),
            ).run_daily()
        )
        self.started = True
        if self.auto_connect_mcp:
            self._integration_task = asyncio.create_task(self._integration_loop())
        if getattr(type(self.channel_manager), "recover_once", None) is not None:
            self._recovery_task = asyncio.create_task(self._recovery_loop())

    def _sync_memory_indexes(self) -> None:
        memory_manager = self.chat_service.memory_processor.memory_manager
        store = getattr(memory_manager, "store", None) or MemoryStore()
        try:
            with self.chat_service.session_factory() as db:
                IdentityRepository().local(db)
                identity_ids = list(db.scalars(select(Identity.id)))
                for identity_id in identity_ids:
                    has_snapshot = db.scalars(
                        select(MemoryFileIndex.id).where(
                            MemoryFileIndex.identity_id == identity_id
                        )
                    ).first() is not None
                    has_incomplete_mutation = db.scalars(
                        select(MemoryMutation.id).where(
                            MemoryMutation.identity_id == identity_id,
                            MemoryMutation.status.in_(("prepared", "file_applied")),
                        )
                    ).first() is not None
                    try:
                        if not has_snapshot or has_incomplete_mutation:
                            rebuild_index(db, store, identity_id)
                        else:
                            sync_changed_index(db, store, identity_id)
                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Memory index startup recovery failed for %s", identity_id
                        )
        except Exception:
            logger.exception("Memory index startup recovery failed")

    async def stop(self) -> None:
        if not self.started:
            return
        if self._dream_task is not None:
            self._dream_task.cancel()
            await asyncio.gather(self._dream_task, return_exceptions=True)
            self._dream_task = None
        if self._intent_task is not None:
            self._intent_task.cancel()
            await asyncio.gather(self._intent_task, return_exceptions=True)
            self._intent_task = None
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            await asyncio.gather(self._recovery_task, return_exceptions=True)
            self._recovery_task = None
        if self._integration_task is not None:
            self._integration_task.cancel()
            await asyncio.gather(self._integration_task, return_exceptions=True)
            self._integration_task = None
        await self.channel_manager.close_all()
        await self.mcp_manager.close_all()
        await self.chat_service.memory_processor.stop()
        self.started = False

    def health(self) -> dict:
        result = {
            "started": self.started,
            "channels": self.channel_manager.list(),
            "mcp_servers": self.mcp_manager.servers(),
            "memory_jobs": self.chat_service.memory_processor.status(),
        }
        if self.channel_start_errors:
            result["degraded"] = True
            result["channel_errors"] = list(self.channel_start_errors)
        return result

    async def _recovery_loop(self) -> None:
        cleanup_counter = 0
        while True:
            try:
                await self.channel_manager.recover_once()
                cleanup_counter += 1
                if cleanup_counter >= 720:
                    self.media_store.cleanup()
                    cleanup_counter = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Channel recovery sweep failed")
            await asyncio.sleep(5)

    async def _reminder_loop(self) -> None:
        while True:
            try:
                await self._deliver_due_reminders()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Standing reminder delivery failed")
            await asyncio.sleep(30)

    async def _deliver_due_reminders(self) -> None:
        intents = StandingIntentService()
        with self.chat_service.session_factory() as db:
            local_due = intents.due_local(db)
            for item in local_due:
                MessageRepository().create(
                    db, conversation_id=item.source_conversation_id,
                    role="assistant", content="提醒：" + item.content, commit=False,
                )
            intents.mark_fired(db, [item.id for item in local_due])
            db.commit()
            due = intents.due_qq(db)
        for item in due:
            adapter = next((
                candidate for candidate in self.channel_manager._adapters.values()
                if getattr(candidate, "channel_config_id", None) == item.channel_config_id
                and getattr(candidate, "owner_user_id", None) == item.target_id
            ), None)
            if adapter is None or not item.target_id or not item.target_id.isdigit():
                continue
            try:
                receipt = await adapter.send(OutboundMessage.text(
                    item.target_id, "提醒：" + item.content,
                    conversation_type="private",
                ))
            except ConnectionError:
                continue
            if receipt.status in {"sent", "unknown"}:
                with self.chat_service.session_factory() as db:
                    intents.mark_fired(db, [item.id])
                    db.commit()

    async def _reconcile_integrations(self) -> None:
        configs = self.mcp_service.runtime_configs()
        await self.mcp_manager.reconcile(configs)
        with self.chat_service.session_factory() as db:
            self._integration_revision = self.settings.get(db, CONFIG_REVISION_KEY) or 0
            self._skills_revision = self.settings.get(db, "skills_registry_revision") or 0

    async def _integration_loop(self) -> None:
        while True:
            try:
                with self.chat_service.session_factory() as db:
                    integration_revision = self.settings.get(db, CONFIG_REVISION_KEY) or 0
                    skills_revision = self.settings.get(db, "skills_registry_revision") or 0
                if integration_revision != self._integration_revision:
                    await self._reconcile_integrations()
                elif skills_revision != self._skills_revision:
                    self.skill_registry.reload(self.skill_service.enabled_overrides())
                    self._skills_revision = skills_revision
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Integration configuration refresh failed")
            await asyncio.sleep(5)

    async def __aenter__(self) -> "RuntimeHost":
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.stop()
