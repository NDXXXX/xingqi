"""Messaging-channel configuration and lifecycle use cases."""

import os
from uuid import uuid4

from zhiyu.channels.manager import ChannelManager, default_manager
from zhiyu.infrastructure.config.keystore import KeyStore, keystore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository


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
        await self.manager.connect(
            "qq",
            endpoint,
            token,
            owner_user_id,
            allow_group_messages,
            group_require_mention,
        )
        return endpoint

    async def stop(self) -> None:
        await self.manager.close_all()

    def status(self) -> dict:
        return self.manager.list()[0]

    def configured_qq(self) -> dict | None:
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                return None
            return {
                "endpoint": config.endpoint,
                "enabled": config.enabled,
                "has_token": config.secret_ref is not None,
                "owner_user_id": config.owner_user_id,
                "allow_group_messages": config.allow_group_messages,
                "group_require_mention": config.group_require_mention,
            }
