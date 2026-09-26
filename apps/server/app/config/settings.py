"""应用配置。"""

import os
from pathlib import Path
import sys

# 数据目录锚定在 server 目录下（config → app → server），
# 与 CWD 无关，独立运行与 Electron 拉起落点一致。
_SERVER_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = Path.home() / ".desktop-ai-companion" if getattr(sys, "frozen", False) else _SERVER_DIR / "data"
_DATA_DIR = Path(os.getenv("COMPANION_DATA_DIR", str(_DEFAULT_DATA_DIR)))
DEFAULT_DB_PATH = _DATA_DIR / "companion.db"
# Skill 目录锚定在项目根（server 上两级）。
DEFAULT_SKILLS_DIR = _SERVER_DIR.parent.parent / "skills"


class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    database_path: Path = DEFAULT_DB_PATH
    skills_dir: Path = Path(os.getenv("SKILLS_DIR", str(DEFAULT_SKILLS_DIR)))
    log_level: str = os.getenv("LOG_LEVEL", "info")
    server_port: int = int(os.getenv("SERVER_PORT", "8001"))
    api_token: str | None = os.getenv("COMPANION_API_TOKEN")
    log_path: Path = _DATA_DIR / "logs" / "companion.log"


settings = Settings()
