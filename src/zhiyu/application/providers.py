"""Provider configuration use cases."""

from __future__ import annotations

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
from zhiyu.infrastructure.database.models import ModelConfig


PROVIDER_FALLBACKS_KEY = "provider_fallbacks"

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

    def detail(self, name: str) -> dict:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, name)
            if provider is None:
                raise ValueError("Provider 不存在")
            fallback_ids = (self.settings.get(db, PROVIDER_FALLBACKS_KEY) or {}).get(provider.id, [])
            by_id = {item.id: item for item in self.providers.list(db)}
            return {
                "id": provider.id,
                "name": provider.name,
                "provider_type": provider.provider_type,
                "enabled": provider.enabled,
                "configured": provider.configured,
                "base_url": provider.base_url,
                "api_key_set": bool(provider.api_key_ref),
                "api_key_env": provider.api_key_ref[4:] if (provider.api_key_ref or "").startswith("env:") else None,
                "models": [self._model_dict(model) for model in provider.models],
                "fallbacks": [by_id[item].name for item in fallback_ids if item in by_id],
            }

    @staticmethod
    def _model_dict(model: ModelConfig) -> dict:
        return {
            "id": model.id, "model_name": model.model_name, "display_name": model.display_name,
            "enabled": model.enabled, "supports_tools": model.supports_tools,
            "supports_streaming": model.supports_streaming, "supports_vision": model.supports_vision,
            "context_window": model.context_window, "max_output_tokens": model.max_output_tokens,
        }

    def update(self, name: str, *, base_url: str | None, enabled: bool,
               api_key: str | None = None, api_key_env: str | None = None,
               clear_api_key: bool = False) -> None:
        if sum(bool(value) for value in (api_key, api_key_env, clear_api_key)) > 1:
            raise ValueError("不能同时替换和清除 API Key")
        if api_key_env and not os.getenv(api_key_env):
            raise ValueError(f"环境变量 {api_key_env} 未设置")
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, name)
            if provider is None:
                raise ValueError("Provider 不存在")
            old_ref = provider.api_key_ref
            new_ref = None
            if api_key:
                new_ref = str(uuid4())
                self.secrets.set(new_ref, api_key)
            elif clear_api_key:
                old_ref = provider.api_key_ref if not (provider.api_key_ref or "").startswith("env:") else None
                provider.api_key_ref = None
            try:
                provider.base_url = base_url
                provider.enabled = enabled
                if new_ref:
                    provider.api_key_ref = new_ref
                elif api_key_env:
                    provider.api_key_ref = f"env:{api_key_env}"
                db.commit()
            except Exception:
                db.rollback()
                if new_ref:
                    self.secrets.delete(new_ref)
                raise
            if (new_ref or api_key_env) and old_ref and not old_ref.startswith("env:"):
                self.secrets.delete(old_ref)
            if clear_api_key and old_ref:
                self.secrets.delete(old_ref)

    def remove(self, name: str) -> None:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, name)
            if provider is None:
                raise ValueError("Provider 不存在")
            fallback_key = self.settings.get(db, PROVIDER_FALLBACKS_KEY) or {}
            fallback_key.pop(provider.id, None)
            for key, values in list(fallback_key.items()):
                fallback_key[key] = [value for value in values if value != provider.id]
            self.settings.set(db, PROVIDER_FALLBACKS_KEY, fallback_key)
            default = self.settings.get(db, DEFAULT_MODEL_KEY) or {}
            if default.get("provider_id") == provider.id:
                self.settings.delete(db, DEFAULT_MODEL_KEY)
            secret_ref = provider.api_key_ref
            self.providers.delete(db, provider)
        if secret_ref and not secret_ref.startswith("env:"):
            self.secrets.delete(secret_ref)

    def add_model(self, provider_name: str, **values) -> dict:
        model_name = (values.get("model_name") or "").strip()
        if not model_name:
            raise ValueError("模型标识不能为空")
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            if provider is None:
                raise ValueError("Provider 不存在")
            if any(item.model_name == model_name for item in provider.models):
                raise ValueError("模型标识已存在")
            values["model_name"] = model_name
            values["display_name"] = values.get("display_name") or model_name
            for key in ("context_window", "max_output_tokens"):
                if values.get(key) is not None and values[key] <= 0:
                    raise ValueError(f"{key} 必须大于 0")
            return self._model_dict(self.providers.create_model(db, provider, **values))

    def update_model(self, provider_name: str, model_id: str, **values) -> dict:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            model = self.providers.get_model(db, provider.id, model_id) if provider else None
            if model is None:
                raise ValueError("模型不存在")
            if "model_name" in values:
                values["model_name"] = values["model_name"].strip()
                if not values["model_name"]:
                    raise ValueError("模型标识不能为空")
                if any(item.id != model.id and item.model_name == values["model_name"] for item in provider.models):
                    raise ValueError("模型标识已存在")
            for key in ("context_window", "max_output_tokens"):
                if values.get(key) is not None and values[key] <= 0:
                    raise ValueError(f"{key} 必须大于 0")
            if values.get("display_name") is None:
                values.pop("display_name", None)
            return self._model_dict(self.providers.update_model(db, model, **values))

    def remove_model(self, provider_name: str, model_id: str) -> None:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            model = self.providers.get_model(db, provider.id, model_id) if provider else None
            if model is None:
                raise ValueError("模型不存在")
            default = self.settings.get(db, DEFAULT_MODEL_KEY) or {}
            if default.get("model_id") == model.id:
                self.settings.delete(db, DEFAULT_MODEL_KEY)
            self.providers.delete_model(db, model)

    def fallbacks(self, provider_name: str) -> list[str]:
        return self.detail(provider_name)["fallbacks"]

    def default_model(self) -> dict | None:
        """Return the global default selected by the same fallback order as chat."""
        with self.session_factory() as db:
            available = [
                item for item in self.providers.list(db)
                if item.enabled and item.configured and any(model.enabled for model in item.models)
            ]
            if not available:
                return None
            configured = self.settings.get(db, DEFAULT_MODEL_KEY) or {}
            provider = next(
                (item for item in available if item.id == configured.get("provider_id")),
                available[0],
            )
            model = next(
                (item for item in provider.models if item.enabled and item.id == configured.get("model_id")),
                next(item for item in provider.models if item.enabled),
            )
            return {"provider": provider.name, "model": model.model_name}

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
            if provider is None or not provider.enabled or not provider.configured:
                raise ValueError("Provider 不存在、未启用或未配置")
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

    def set_vision(self, provider_name: str, model_name: str, enabled: bool) -> None:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            if provider is None or not provider.enabled:
                raise ValueError("Provider 不存在或未启用")
            model = next(
                (item for item in provider.models if item.model_name == model_name),
                None,
            )
            if model is None:
                raise ValueError("模型不存在")
            self.providers.update_model(db, model, supports_vision=enabled)

    def set_fallbacks(self, provider_name: str, fallback_names: list[str]) -> None:
        with self.session_factory() as db:
            provider = self.providers.get_by_name(db, provider_name)
            if provider is None or not provider.enabled or not provider.configured:
                raise ValueError("主 Provider 不存在、未启用或未配置")
            fallback_ids: list[str] = []
            for name in fallback_names:
                fallback = self.providers.get_by_name(db, name)
                if fallback is None or not fallback.enabled or not fallback.configured:
                    raise ValueError(f"备用 Provider 不存在、未启用或未配置：{name}")
                if fallback.id == provider.id:
                    raise ValueError("主 Provider 不能作为自己的备用")
                if fallback.id not in fallback_ids:
                    fallback_ids.append(fallback.id)
            mapping = self.settings.get(db, PROVIDER_FALLBACKS_KEY) or {}
            mapping[provider.id] = fallback_ids
            self.settings.set(db, PROVIDER_FALLBACKS_KEY, mapping)

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
