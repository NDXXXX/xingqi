"""QQ 与 MCP 持久化配置仓储。"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChannelConfig, McpServerConfig


class ChannelConfigRepository:
    def list_enabled(self, db: Session) -> list[ChannelConfig]:
        return list(db.scalars(select(ChannelConfig).where(ChannelConfig.enabled.is_(True))))

    def get(self, db: Session, channel: str) -> ChannelConfig | None:
        return db.scalars(select(ChannelConfig).where(ChannelConfig.channel == channel)).first()

    def upsert(
        self,
        db: Session,
        channel: str,
        endpoint: str,
        secret_ref: str | None,
        *,
        enabled: bool = True,
        auto_connect: bool = True,
        owner_user_id: str | None = None,
        allow_group_messages: bool | None = None,
        group_require_mention: bool | None = None,
    ) -> ChannelConfig:
        config = self.get(db, channel)
        if config is None:
            config = ChannelConfig(
                id=str(uuid4()),
                channel=channel,
                name=channel.upper(),
                endpoint=endpoint,
                secret_ref=secret_ref,
                owner_user_id=owner_user_id,
                allow_group_messages=bool(allow_group_messages),
                group_require_mention=(
                    True if group_require_mention is None else group_require_mention
                ),
                enabled=enabled,
                auto_connect=auto_connect,
            )
            db.add(config)
        else:
            config.endpoint = endpoint
            config.secret_ref = secret_ref
            config.owner_user_id = owner_user_id
            if allow_group_messages is not None:
                config.allow_group_messages = allow_group_messages
            if group_require_mention is not None:
                config.group_require_mention = group_require_mention
            config.enabled = enabled
            config.auto_connect = auto_connect
        db.commit()
        db.refresh(config)
        return config

    def disable(self, db: Session, channel: str) -> None:
        config = self.get(db, channel)
        if config:
            config.enabled = False
            config.auto_connect = False
            db.commit()


class McpConfigRepository:
    def list(self, db: Session) -> list[McpServerConfig]:
        return list(db.scalars(select(McpServerConfig).order_by(McpServerConfig.name)))

    def list_auto_connect(self, db: Session) -> list[McpServerConfig]:
        return list(
            db.scalars(
                select(McpServerConfig).where(
                    McpServerConfig.enabled.is_(True),
                    McpServerConfig.auto_connect.is_(True),
                )
            )
        )

    def get(self, db: Session, name: str) -> McpServerConfig | None:
        return db.scalars(select(McpServerConfig).where(McpServerConfig.name == name)).first()

    def upsert(
        self,
        db: Session,
        name: str,
        command: str,
        args: list[str],
        *,
        tool_allowlist: list[str] | None = None,
    ) -> McpServerConfig:
        config = self.get(db, name)
        if config is None:
            config = McpServerConfig(
                id=str(uuid4()),
                name=name,
                command=command,
                args_json=json.dumps(args, ensure_ascii=False),
                tool_allowlist_json=json.dumps(tool_allowlist or [], ensure_ascii=False),
            )
            db.add(config)
        else:
            config.command = command
            config.args_json = json.dumps(args, ensure_ascii=False)
            if tool_allowlist is not None:
                config.tool_allowlist_json = json.dumps(tool_allowlist, ensure_ascii=False)
            config.enabled = True
            config.auto_connect = True
        db.commit()
        db.refresh(config)
        return config

    def disable(self, db: Session, name: str) -> None:
        config = self.get(db, name)
        if config:
            config.enabled = False
            config.auto_connect = False
            db.commit()

    @staticmethod
    def args(config: McpServerConfig) -> list[str]:
        value = json.loads(config.args_json)
        return value if isinstance(value, list) else []

    @staticmethod
    def tool_allowlist(config: McpServerConfig) -> list[str]:
        value = json.loads(config.tool_allowlist_json)
        return value if isinstance(value, list) else []
