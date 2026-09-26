"""本地滚动日志配置。"""

import logging
from logging.handlers import RotatingFileHandler

from .settings import settings


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "name", None) == "companion-file" for handler in root.handlers):
        return
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.name = "companion-file"
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
