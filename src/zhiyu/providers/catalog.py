"""静态 Provider 类型元数据，不加载运行时实现或密钥。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCatalogEntry:
    implementation: str
    default_base_url: str
    default_models: tuple[str, ...]


PROVIDER_CATALOG: dict[str, ProviderCatalogEntry] = {
    "deepseek": ProviderCatalogEntry(
        "openai_compatible", "https://api.deepseek.com", ("deepseek-chat", "deepseek-reasoner")
    ),
    "minimax": ProviderCatalogEntry(
        "openai_compatible", "https://api.minimax.io/v1", ("MiniMax-M3", "MiniMax-M2.7")
    ),
    "kimi": ProviderCatalogEntry(
        "openai_compatible", "https://api.moonshot.cn/v1", ("moonshot-v1-8k", "kimi-k2")
    ),
    "openai": ProviderCatalogEntry(
        "openai_compatible", "https://api.openai.com/v1", ("gpt-4o-mini", "gpt-4o")
    ),
    "anthropic": ProviderCatalogEntry(
        "anthropic", "https://api.anthropic.com", ("claude-sonnet-4-5", "claude-haiku-4-5")
    ),
}
