"""应用设置仓储。"""

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AppSetting


class SettingRepository:
    def get(self, db: Session, key: str) -> Any | None:
        setting = db.get(AppSetting, key)
        return json.loads(setting.value_json) if setting else None

    def set(self, db: Session, key: str, value: Any) -> AppSetting:
        setting = db.get(AppSetting, key)
        payload = json.dumps(value, ensure_ascii=False)
        if setting is None:
            setting = AppSetting(key=key, value_json=payload)
            db.add(setting)
        else:
            setting.value_json = payload
        db.commit()
        db.refresh(setting)
        return setting

    def delete(self, db: Session, key: str) -> bool:
        setting = db.get(AppSetting, key)
        if setting is None:
            return False
        db.delete(setting)
        db.commit()
        return True
