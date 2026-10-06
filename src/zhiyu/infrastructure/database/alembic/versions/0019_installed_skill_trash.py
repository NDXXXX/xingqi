"""Add trash timestamp to installed Skills."""

from alembic import op
import sqlalchemy as sa


revision = "0019_installed_skill_trash"
down_revision = "0018_mcp_skills_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("installed_skills", sa.Column("trashed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("installed_skills", "trashed_at")
