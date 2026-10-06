"""QQ 与 MCP 持久化配置仓储。"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChannelConfig, InstalledSkill, McpRuntimeState, McpServerConfig, utcnow


class ChannelConfigRepository:
    def list_enabled(self, db: Session) -> list[ChannelConfig]:
        return list(db.scalars(select(ChannelConfig).where(ChannelConfig.enabled.is_(True))))

    def list_auto_connect(self, db: Session) -> list[ChannelConfig]:
        return list(
            db.scalars(
                select(ChannelConfig).where(
                    ChannelConfig.enabled.is_(True),
                    ChannelConfig.auto_connect.is_(True),
                )
            )
        )

    def get(
        self, db: Session, channel: str, account_id: str | None = None
    ) -> ChannelConfig | None:
        statement = select(ChannelConfig).where(ChannelConfig.channel == channel)
        if account_id is not None:
            statement = statement.where(ChannelConfig.account_id == account_id)
        return db.scalars(statement.order_by(ChannelConfig.created_at)).first()

    def get_by_id(self, db: Session, config_id: str) -> ChannelConfig | None:
        return db.get(ChannelConfig, config_id)

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
        account_id: str = "qq-onebot-default",
        driver: str = "onebot_reverse_ws",
    ) -> ChannelConfig:
        config = self.get(db, channel, account_id)
        if config is None:
            config = ChannelConfig(
                id=str(uuid4()),
                channel=channel,
                account_id=account_id,
                driver=driver,
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
            config.driver = driver
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
        enabled: bool = True,
    ) -> McpServerConfig:
        config = self.get(db, name)
        if config is None:
            config = McpServerConfig(
                id=str(uuid4()),
                name=name,
                transport="stdio",
                command=command,
                args_json=json.dumps(args, ensure_ascii=False),
                tool_allowlist_json=json.dumps(tool_allowlist or [], ensure_ascii=False),
                legacy_all_tools=False,
                enabled=enabled,
                auto_connect=enabled,
            )
            db.add(config)
        else:
            config.transport = "stdio"
            config.command = command
            config.args_json = json.dumps(args, ensure_ascii=False)
            if tool_allowlist is not None:
                config.tool_allowlist_json = json.dumps(tool_allowlist, ensure_ascii=False)
                config.legacy_all_tools = False
            config.enabled = enabled
            config.auto_connect = enabled
        db.commit()
        db.refresh(config)
        return config

    def disable(self, db: Session, name: str) -> None:
        config = self.get(db, name)
        if config:
            config.enabled = False
            config.auto_connect = False
            db.commit()

    def set_enabled(self, db: Session, name: str, enabled: bool) -> McpServerConfig:
        config = self.get(db, name)
        if config is None:
            raise ValueError("MCP Server 不存在")
        config.enabled = enabled
        config.auto_connect = enabled
        db.commit()
        db.refresh(config)
        return config

    def update_fields(self, db: Session, name: str, **fields) -> McpServerConfig:
        config = self.get(db, name)
        if config is None:
            raise ValueError("MCP Server 不存在")
        for key, value in fields.items():
            setattr(config, key, value)
        config.updated_at = utcnow()
        db.commit()
        db.refresh(config)
        return config

    def remove(self, db: Session, name: str) -> McpServerConfig | None:
        config = self.get(db, name)
        if config is not None:
            db.delete(config)
            db.commit()
        return config

    @staticmethod
    def args(config: McpServerConfig) -> list[str]:
        value = json.loads(config.args_json)
        return value if isinstance(value, list) else []

    @staticmethod
    def tool_allowlist(config: McpServerConfig) -> list[str]:
        value = json.loads(config.tool_allowlist_json)
        return value if isinstance(value, list) else []

    @staticmethod
    def json_field(config: McpServerConfig, field: str) -> dict | list:
        value = json.loads(getattr(config, field))
        return value if isinstance(value, (dict, list)) else {}


class McpRuntimeStateRepository:
    def get(self, db: Session, server_config_id: str) -> McpRuntimeState | None:
        return db.get(McpRuntimeState, server_config_id)

    def upsert(self, db: Session, server_config_id: str, **values) -> McpRuntimeState:
        state = self.get(db, server_config_id)
        if state is None:
            state = McpRuntimeState(
                server_config_id=server_config_id,
                status="stopped",
                updated_at=utcnow(),
            )
            db.add(state)
        for key, value in values.items():
            setattr(state, key, value)
        state.updated_at = utcnow()
        db.commit()
        db.refresh(state)
        return state

    def delete(self, db: Session, server_config_id: str) -> None:
        state = self.get(db, server_config_id)
        if state is not None:
            db.delete(state)
            db.commit()


class InstalledSkillRepository:
    def list(self, db: Session) -> list[InstalledSkill]:
        return list(db.scalars(select(InstalledSkill).order_by(InstalledSkill.name)))

    def get(self, db: Session, name: str) -> InstalledSkill | None:
        return db.get(InstalledSkill, name)

    def save(self, db: Session, **values) -> InstalledSkill:
        item = self.get(db, values["name"])
        if item is None:
            item = InstalledSkill(**values)
            db.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
            item.updated_at = utcnow()
        db.flush()
        return item

    def delete(self, db: Session, name: str) -> None:
        item = self.get(db, name)
        if item is not None:
            db.delete(item)
