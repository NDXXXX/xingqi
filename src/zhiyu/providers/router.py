"""LLM Router：Agent 不直接调用模型 SDK，统一经由此路由。"""

from dataclasses import dataclass
import os

from zhiyu.infrastructure.config.keystore import keystore
from zhiyu.infrastructure.database.models import Provider
from .catalog import PROVIDER_CATALOG
from .anthropic import AnthropicProvider
from .base import AIProvider
from .openai_compatible import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderSpec:
    """provider_type 的静态元信息。"""

    provider_cls: type[AIProvider]
    default_base_url: str
    default_models: tuple[str, ...]


_IMPLEMENTATIONS: dict[str, type[AIProvider]] = {
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}

PROVIDER_SPECS: dict[str, ProviderSpec] = {
    provider_type: ProviderSpec(
        _IMPLEMENTATIONS[entry.implementation], entry.default_base_url, entry.default_models
    )
    for provider_type, entry in PROVIDER_CATALOG.items()
}


class ProviderRouter:
    """根据 Provider 配置实例化对应 Provider，并从 Keychain 取回 API Key。"""

    def get_provider(self, config: Provider) -> AIProvider:
        spec = PROVIDER_SPECS[config.provider_type]
        if config.api_key_ref and config.api_key_ref.startswith("env:"):
            api_key = os.getenv(config.api_key_ref.removeprefix("env:"))
        else:
            api_key = keystore.get(config.api_key_ref) if config.api_key_ref else None
        return spec.provider_cls(api_key=api_key, base_url=config.base_url or spec.default_base_url)


provider_router = ProviderRouter()
