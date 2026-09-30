"""Secrets stored through the platform keyring.

数据库只保存 api_key_ref，不保存明文 Key。
"""

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "zhiyu"
LEGACY_SERVICE = "desktop-ai-companion"


class KeyStore:
    def set(self, ref: str, api_key: str) -> None:
        keyring.set_password(SERVICE, ref, api_key)

    def get(self, ref: str) -> str | None:
        return keyring.get_password(SERVICE, ref) or keyring.get_password(LEGACY_SERVICE, ref)

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(SERVICE, ref)
        except PasswordDeleteError:
            pass
        try:
            keyring.delete_password(LEGACY_SERVICE, ref)
        except PasswordDeleteError:
            pass

    def available(self) -> tuple[bool, str]:
        backend = keyring.get_keyring()
        try:
            priority = float(getattr(backend, "priority", 0))
        except (TypeError, ValueError, KeyringError):
            priority = 0
        return priority > 0, backend.__class__.__name__


keystore = KeyStore()
