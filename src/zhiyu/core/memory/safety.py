"""拒绝把可直接访问账户的秘密写入普通长期记忆。"""

import re

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:api[\s_-]*key|access[\s_-]*token|password|secret|密码|验证码|私钥|助记词|恢复码)"
        r"\s*(?:是|为|[:：=])\s*\S+"
    ),
    re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|xox[baprs]-[a-z0-9-]{16,})\b"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[\dXx]\b"),
)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)
