"""Rename the local desktop identity and conversations to local."""

from alembic import op

revision = "0006_local_identity"
down_revision = "0005_qq_reverse_ws"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE identities SET channel = 'local' WHERE channel = 'desktop'")
    op.execute("UPDATE conversations SET channel = 'local' WHERE channel = 'desktop'")


def downgrade() -> None:
    op.execute("UPDATE identities SET channel = 'desktop' WHERE channel = 'local'")
    op.execute("UPDATE conversations SET channel = 'desktop' WHERE channel = 'local'")
