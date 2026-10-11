"""Share existing default assistant user facts with all character workspaces."""

from alembic import op
import sqlalchemy as sa


revision = "0025_m2_shared_memory"
down_revision = "0024_m1_chat_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE memories SET shared = 1 "
            "WHERE identity_id = '00000000-0000-0000-0000-000000000001' "
            "AND character_id IS NULL "
            "AND type IN ('profile', 'preference', 'fact', 'goal', 'project') "
            "AND (file_path IS NULL OR file_path NOT LIKE '%/IDENTITY.md')"
        )
    )


def downgrade():
    # Shared user information is user data; never erase or privatize it on downgrade.
    pass
