"""Cross-platform runtime settings for the CLI application."""

import os
from pathlib import Path
import warnings


def _env(name: str, legacy: str | None = None, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    if legacy and (value := os.getenv(legacy)) is not None:
        warnings.warn(
            f"{legacy} 已弃用，请改用 {name}",
            FutureWarning,
            stacklevel=2,
        )
        return value
    return default


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(
            _env("ZHIYU_DATA_DIR", "COMPANION_DATA_DIR", str(Path.home() / ".zhiyu"))
            or Path.home() / ".zhiyu"
        ).expanduser()
        self.database_path = self.data_dir / "companion.db"
        self.memory_dir = self.data_dir / "memory"
        self.database_url = _env(
            "ZHIYU_DATABASE_URL",
            "DATABASE_URL",
            f"sqlite:///{self.database_path}",
        ) or f"sqlite:///{self.database_path}"
        self.user_skills_dir = Path(
            _env("ZHIYU_SKILLS_DIR", "SKILLS_DIR", str(self.data_dir / "skills"))
            or self.data_dir / "skills"
        ).expanduser()
        self.builtin_skills_dir = Path(__file__).resolve().parents[2] / "builtin_skills"
        self.log_level = _env("ZHIYU_LOG_LEVEL", "LOG_LEVEL", "info") or "info"
        self.log_path = self.data_dir / "logs" / "zhiyu.log"


settings = Settings()
