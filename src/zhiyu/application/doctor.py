"""Local environment diagnostics."""

from dataclasses import dataclass
import os
import sys

from sqlalchemy import text

from zhiyu.infrastructure.config.keystore import keystore
from zhiyu.infrastructure.config.settings import settings
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.integrations.skills.registry import default_registry


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str


def run_checks() -> list[Check]:
    checks = [
        Check(
            "Python",
            "ok" if sys.version_info >= (3, 12) else "fail",
            sys.version.split()[0],
        )
    ]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    writable = os.access(settings.data_dir, os.W_OK)
    checks.append(Check("数据目录", "ok" if writable else "fail", str(settings.data_dir)))

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            providers = ProviderRepository().list(db)
        checks.append(Check("数据库", "ok", str(settings.database_path)))
        checks.append(Check("Provider", "ok" if providers else "warn", f"已配置 {len(providers)} 个"))
    except Exception as exc:
        checks.append(Check("数据库", "fail", str(exc)))

    try:
        available, backend = keystore.available()
        checks.append(Check("Keyring", "ok" if available else "warn", backend))
    except Exception as exc:
        checks.append(Check("Keyring", "warn", str(exc)))

    checks.append(Check("Skills", "ok", f"已加载 {len(default_registry.all())} 个"))
    return checks
