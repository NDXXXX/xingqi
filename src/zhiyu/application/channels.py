"""Messaging-channel configuration and lifecycle use cases."""

import os
from uuid import uuid4

from zhiyu.channels.manager import ChannelManager, default_manager
from zhiyu.infrastructure.config.keystore import KeyStore, keystore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository
from zhiyu.infrastructure.database.repositories.channel_repository import (
    ChannelEventRepository,
    ChannelGroupPolicyRepository,
)


class ChannelService:
    def __init__(
        self,
        session_factory=SessionLocal,
        manager: ChannelManager = default_manager,
        secrets: KeyStore = keystore,
    ) -> None:
        self.session_factory = session_factory
        self.manager = manager
        self.secrets = secrets
        self.configs = ChannelConfigRepository()
        self.events = ChannelEventRepository()
        self.group_policies = ChannelGroupPolicyRepository()

    def configure_qq(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        token_env: str | None = None,
        clear_token: bool = False,
        owner_user_id: str | None = None,
        clear_owner_user_id: bool = False,
        allow_group_messages: bool | None = None,
        group_require_mention: bool | None = None,
    ) -> None:
        if sum((bool(token), bool(token_env), clear_token)) > 1:
            raise ValueError("Token、Token 环境变量和清除 Token 只能选择一个")
        if owner_user_id and clear_owner_user_id:
            raise ValueError("主人 QQ ID 和清除主人 QQ ID 只能选择一个")
        if owner_user_id is not None and not owner_user_id.strip():
            raise ValueError("主人 QQ ID 不能为空")
        if token_env and not os.getenv(token_env):
            raise ValueError(f"环境变量 {token_env} 未设置")
        with self.session_factory() as db:
            existing = self.configs.get(db, "qq")
            old_ref = existing.secret_ref if existing else None
            secret_ref = old_ref
            configured_owner = existing.owner_user_id if existing else None
            if owner_user_id:
                configured_owner = owner_user_id.strip()
            elif clear_owner_user_id:
                configured_owner = None
            if token_env:
                secret_ref = f"env:{token_env}"
            elif token:
                secret_ref = str(uuid4())
                self.secrets.set(secret_ref, token)
            elif clear_token:
                secret_ref = None
            self.configs.upsert(
                db,
                "qq",
                endpoint,
                secret_ref,
                owner_user_id=configured_owner,
                allow_group_messages=allow_group_messages,
                group_require_mention=group_require_mention,
                account_id="qq-onebot-default",
            )
            if old_ref and old_ref != secret_ref and not old_ref.startswith("env:"):
                self.secrets.delete(old_ref)

    async def start_qq(self) -> str:
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                raise ValueError("QQ 尚未配置，请先运行 zhiyu qq configure")
            if not config.owner_user_id:
                raise ValueError(
                    "尚未配置主人 QQ ID，请运行 zhiyu qq configure --owner-user-id <QQ号>"
                )
            if config.secret_ref and config.secret_ref.startswith("env:"):
                token = os.getenv(config.secret_ref.removeprefix("env:"))
            else:
                token = self.secrets.get(config.secret_ref) if config.secret_ref else None
            endpoint = config.endpoint
            owner_user_id = config.owner_user_id
            allow_group_messages = config.allow_group_messages
            group_require_mention = config.group_require_mention
            channel_config_id = config.id
            account_id = config.account_id
            if config.secret_ref and token is None:
                raise ValueError("QQ Access Token 无法从 Keychain 或环境变量读取")
        await self.manager.connect(
            "qq",
            endpoint,
            token,
            owner_user_id,
            allow_group_messages,
            group_require_mention,
            channel_config_id=channel_config_id,
            account_id=account_id,
        )
        return endpoint

    async def start_auto_connect(self) -> list[str]:
        with self.session_factory() as db:
            configs = self.configs.list_auto_connect(db)
        qq_configs = [item for item in configs if item.channel == "qq"]
        if len(qq_configs) > 1:
            raise ValueError("当前版本尚不支持多个 QQ 账号同时启用")
        started = []
        if qq_configs:
            started.append(await self.start_qq())
        return started

    async def stop(self) -> None:
        await self.manager.close_all()

    def status(self) -> dict:
        return self.manager.list()[0]

    def configured_qq(self) -> dict | None:
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                return None
            if config.secret_ref and config.secret_ref.startswith("env:"):
                token_readable = bool(os.getenv(config.secret_ref.removeprefix("env:")))
            else:
                token_readable = bool(
                    self.secrets.get(config.secret_ref) if config.secret_ref else None
                )
            return {
                "endpoint": config.endpoint,
                "id": config.id,
                "account_id": config.account_id,
                "driver": config.driver,
                "enabled": config.enabled,
                "has_token": config.secret_ref is not None,
                "token_readable": token_readable,
                "owner_user_id": config.owner_user_id,
                "allow_group_messages": config.allow_group_messages,
                "group_require_mention": config.group_require_mention,
            }

    def set_group_policy(
        self,
        group_id: str,
        *,
        enabled: bool,
        require_mention: bool = True,
        tool_allowlist: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> dict:
        if not group_id.strip():
            raise ValueError("群 ID 不能为空")
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                raise ValueError("QQ 尚未配置")
            policy = self.group_policies.upsert(
                db,
                config.id,
                group_id.strip(),
                enabled=enabled,
                require_mention=require_mention,
                tool_allowlist=tool_allowlist,
                system_prompt=system_prompt,
            )
            return self._policy_dict(policy)

    def list_group_policies(self) -> list[dict]:
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                return []
            return [
                self._policy_dict(item)
                for item in self.group_policies.list(db, config.id)
            ]

    def list_events(self, limit: int = 50) -> list[dict]:
        from sqlalchemy import select
        from zhiyu.infrastructure.database.models import ChannelEvent

        with self.session_factory() as db:
            rows = list(
                db.scalars(
                    select(ChannelEvent)
                    .order_by(ChannelEvent.received_at.desc())
                    .limit(limit)
                )
            )
            return [
                {
                    "id": item.id,
                    "status": item.status,
                    "attempts": item.attempts,
                    "last_error": item.last_error,
                    "received_at": item.received_at,
                    "completed_at": item.completed_at,
                }
                for item in rows
            ]

    def replay_event(self, event_id: str) -> None:
        with self.session_factory() as db:
            event = self.events.get(db, event_id)
            if event is None:
                raise ValueError("渠道事件不存在")
            if event.status not in {"failed", "pending"}:
                raise ValueError("只有失败或待处理事件可以 replay")
            event.status = "pending"
            event.attempts = 0
            event.completed_at = None
            event.last_error = None
            db.commit()

    def list_deliveries(self, limit: int = 50) -> list[dict]:
        return self.manager.reliability.list_deliveries(limit)

    def retry_delivery(self, delivery_id: str, *, allow_unknown: bool = False) -> str:
        return self.manager.reliability.queue_delivery_retry(
            delivery_id, allow_unknown=allow_unknown
        )

    def _policy_dict(self, policy) -> dict:
        return {
            "group_id": policy.external_group_id,
            "enabled": policy.enabled,
            "require_mention": policy.require_mention,
            "tool_allowlist": self.group_policies.tool_allowlist(policy),
            "system_prompt": policy.system_prompt,
        }
