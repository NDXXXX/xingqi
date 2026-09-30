"""Disable legacy forward QQ endpoints before switching to reverse WebSocket."""

from alembic import op

revision = "0005_qq_reverse_ws"
down_revision = "0004_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE channel_configs SET enabled = 0, auto_connect = 0 WHERE channel = 'qq'")


def downgrade() -> None:
    # A reverse listener address must not become a forward destination either.
    op.execute("UPDATE channel_configs SET enabled = 0, auto_connect = 0 WHERE channel = 'qq'")
