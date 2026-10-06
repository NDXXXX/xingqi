"""时效性记忆的确定性状态规则。"""

from datetime import timedelta

from zhiyu.infrastructure.database.models import Memory, utcnow

CONFIRMATION_DAYS = 90


def needs_confirmation(memory: Memory, now=None) -> bool:
    if memory.type not in {"goal", "project"} or memory.tier != "core" or memory.status != "active":
        return False
    observed = memory.last_evidence_at or memory.observed_at or memory.created_at
    return observed is not None and (now or utcnow()) - observed >= timedelta(days=CONFIRMATION_DAYS)
