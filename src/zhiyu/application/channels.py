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
    ) -> None:
        if sum((bool(token), bool(token_env), clear_token)) > 1:
            raise ValueError("Token、Token 环境变量和清除 Token 只能选择一个")
        if token_env and not os.getenv(token_env):
            raise ValueError(f"环境变量 {token_env} 未设置")
        with self.session_factory() as db:
            existing = self.configs.get(db, "qq")
            old_ref = existing.secret_ref if existing else None
            secret_ref = old_ref
            if token_env:
                secret_ref = f"env:{token_env}"
            elif token:
                secret_ref = str(uuid4())
                self.secrets.set(secret_ref, token)
            elif clear_token:
                secret_ref = None
            self.configs.upsert(db, "qq", endpoint, secret_ref)
            if old_ref and old_ref != secret_ref and not old_ref.startswith("env:"):
                self.secrets.delete(old_ref)

    async def start_qq(self) -> str:
        with self.session_factory() as db:
            config = self.configs.get(db, "qq")
            if config is None:
                raise ValueError("QQ 尚未配置，请先运行 zhiyu qq configure")
            if config.secret_ref and config.secret_ref.startswith("env:"):
                token = os.getenv(config.secret_ref.removeprefix("env:"))
            else:
                token = self.secrets.get(config.secret_ref) if config.secret_ref else None
            endpoint = config.endpoint
        await self.manager.connect("qq", endpoint, token)
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
            }
