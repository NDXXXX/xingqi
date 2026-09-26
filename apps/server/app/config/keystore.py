"""API Key 安全存储（macOS Keychain / Windows Credential Manager）。

数据库只保存 api_key_ref，不保存明文 Key。
"""

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "desktop-ai-companion"


class KeyStore:
    def set(self, ref: str, api_key: str) -> None:
        keyring.set_password(SERVICE, ref, api_key)

    def get(self, ref: str) -> str | None:
        return keyring.get_password(SERVICE, ref)

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(SERVICE, ref)
        except PasswordDeleteError:
            pass


keystore = KeyStore()
