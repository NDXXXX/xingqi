"""统一的 Provider / Model 选择优先级。"""

from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Conversation, ModelConfig, Provider
from zhiyu.infrastructure.database.repositories.character_repository import CharacterRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository

DEFAULT_MODEL_KEY = "default_model"


class ProviderSelectionError(ValueError):
    pass


def select_provider_model(
    db: Session,
    conversation: Conversation,
    requested_provider_id: str | None = None,
    requested_model_name: str | None = None,
) -> tuple[Provider, ModelConfig]:
    providers = [
        provider
        for provider in ProviderRepository().list(db)
        if provider.enabled and provider.configured
    ]
    if not providers:
        raise ProviderSelectionError("没有可用的 Provider，请先运行 zhiyu provider add")

    by_model_id = {
        model.id: (provider, model)
        for provider in providers
        for model in provider.models
        if model.enabled
    }
    default = SettingRepository().get(db, DEFAULT_MODEL_KEY) or {}

    provider: Provider | None = None
    if requested_provider_id:
        provider = next((item for item in providers if item.id == requested_provider_id), None)
        if provider is None:
            raise ProviderSelectionError("指定的 Provider 不可用")
    elif conversation.model_id:
        provider = next(
            (
                item
                for item in providers
                if any(model.enabled and model.model_name == conversation.model_id for model in item.models)
            ),
            None,
        )
    if provider is None and conversation.character_id:
        character = CharacterRepository().get(db, conversation.character_id)
        selected = by_model_id.get(character.default_model_id) if character else None
        if selected:
            provider = selected[0]
    if provider is None:
        provider = next((item for item in providers if item.id == default.get("provider_id")), providers[0])

    enabled_models = [model for model in provider.models if model.enabled]
    if not enabled_models:
        raise ProviderSelectionError("Provider 未配置可用模型")

    model: ModelConfig | None = None
    if requested_model_name:
        model = next((item for item in enabled_models if item.model_name == requested_model_name), None)
        if model is None:
            raise ProviderSelectionError("指定的模型不属于当前 Provider 或已停用")
    elif conversation.model_id:
        model = next((item for item in enabled_models if item.model_name == conversation.model_id), None)
    if model is None and conversation.character_id:
        character = CharacterRepository().get(db, conversation.character_id)
        model = next(
            (item for item in enabled_models if character and item.id == character.default_model_id),
            None,
        )
    if model is None and provider.id == default.get("provider_id"):
        model = next((item for item in enabled_models if item.id == default.get("model_id")), None)
    return provider, model or enabled_models[0]
