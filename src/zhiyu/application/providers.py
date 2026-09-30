"""Provider configuration use cases."""

from dataclasses import dataclass
import os
from uuid import uuid4

from zhiyu.core.providers.base import LLMResponse
from zhiyu.core.providers.router import PROVIDER_SPECS, ProviderRouter, provider_router
from zhiyu.core.providers.selection import DEFAULT_MODEL_KEY
from zhiyu.infrastructure.config.keystore import KeyStore, keystore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository


@dataclass(slots=True)
class ProviderSummary:
    id: str
    name: str
    provider_type: str
    enabled: bool
    configured: bool
    models: list[str]


class ProviderService:
    def __init__(
        self,
        session_factory=SessionLocal,
        secrets: KeyStore = keystore,
        router: ProviderRouter = provider_router,
    ) -> None:
        self.session_factory = session_factory
        self.secrets = secrets
        self.router = router
        self.providers = ProviderRepository()
        self.settings = SettingRepository()

    def list(self) -> list[ProviderSummary]:
        with self.session_factory() as db:
            return [
                ProviderSummary(
                    id=item.id,
                    name=item.name,
                    provider_type=item.provider_type,
                    enabled=item.enabled,
                    configured=item.configured,
                    models=[model.model_name for model in item.models if model.enabled],
                )
                for item in self.providers.list(db)
            ]

    def add(
        self,
        *,
        name: str,
        provider_type: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
    ) -> ProviderSummary:
        if provider_type not in PROVIDER_SPECS:
            raise ValueError(f"不支持的 Provider 类型: {provider_type}")
        if bool(api_key) == bool(api_key_env):
            raise ValueError("必须且只能提供 API Key 或 API Key 环境变量")
        if api_key_env and not os.getenv(api_key_env):
            raise ValueError(f"环境变量 {api_key_env} 未设置")

        with self.session_factory() as db:
            if self.providers.get_by_name(db, name):
                raise ValueError("Provider 名称已存在")
            secret_ref = f"env:{api_key_env}" if api_key_env else str(uuid4())
            if api_key:
                self.secrets.set(secret_ref, api_key)
            try:
                provider = self.providers.create(
                    db,
                    name=name,
                    provider_type=provider_type,
                    api_key_ref=secret_ref,
                    base_url=base_url,
                )
            except Exception:
                if api_key:
                    self.secrets.delete(secret_ref)
                raise
            return ProviderSummary(
                id=provider.id,
                name=provider.name,
                provider_type=provider.provider_type,
                enabled=provider.enabled,
                configured=provider.configured,
                models=[model.model_name for model in provider.models if model.enabled],
            )

    def set_default(self, provider_name: str, model_name: str) -> None:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            if provider is None or not provider.enabled:
                raise ValueError("Provider 不存在或未启用")
            model = next(
                (item for item in provider.models if item.enabled and item.model_name == model_name),
                None,
            )
            if model is None:
                raise ValueError("模型不存在或未启用")
            self.settings.set(
                db,
                DEFAULT_MODEL_KEY,
                {"provider_id": provider.id, "model_id": model.id},
            )

    async def test(self, provider_name: str, model_name: str | None = None) -> str:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            if provider is None:
                raise ValueError("Provider 不存在")
            models = [item for item in provider.models if item.enabled]
            model = next((item for item in models if item.model_name == model_name), None) if model_name else None
            model = model or (models[0] if models else None)
            if model is None:
                raise ValueError("Provider 没有可用模型")
            client = self.router.get_provider(provider)
            result = await client.chat(
                messages=[{"role": "user", "content": "Reply with OK."}],
                model=model.model_name,
                stream=False,
            )
            if not isinstance(result, LLMResponse):
                raise RuntimeError("Provider 返回了无效响应")
            return result.content or ""
