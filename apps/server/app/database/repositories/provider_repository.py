"""Provider 仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...providers.router import PROVIDER_SPECS
from ..models import ModelConfig, Provider


class ProviderRepository:
    def list(self, db: Session) -> list[Provider]:
        return list(
            db.scalars(select(Provider).options(selectinload(Provider.models)).order_by(Provider.name))
        )

    def get(self, db: Session, provider_id: str) -> Provider | None:
        return db.scalars(
            select(Provider).options(selectinload(Provider.models)).where(Provider.id == provider_id)
        ).first()

    def create(
        self,
        db: Session,
        *,
        name: str,
        provider_type: str,
        api_key_ref: str | None,
        base_url: str | None = None,
    ) -> Provider:
        provider = Provider(
            id=str(uuid4()),
            name=name,
            provider_type=provider_type,
            api_key_ref=api_key_ref,
            base_url=base_url,
        )
        # 为已知 provider_type 种子默认模型
        spec = PROVIDER_SPECS.get(provider_type)
        if spec:
            for model_name in spec.default_models:
                provider.models.append(
                    ModelConfig(id=str(uuid4()), model_name=model_name, display_name=model_name)
                )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return provider
