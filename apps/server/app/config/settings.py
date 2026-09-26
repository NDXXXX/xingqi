"""应用配置。"""

import os
from pathlib import Path

# 数据目录锚定在 server 目录下（config → app → server），
# 与 CWD 无关，独立运行与 Electron 拉起落点一致。
_SERVER_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _SERVER_DIR / "data" / "companion.db"


class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    database_path: Path = DEFAULT_DB_PATH
    log_level: str = os.getenv("LOG_LEVEL", "info")
    server_port: int = int(os.getenv("SERVER_PORT", "8001"))


settings = Settings()
