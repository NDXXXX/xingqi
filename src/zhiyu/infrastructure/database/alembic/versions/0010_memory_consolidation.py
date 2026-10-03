"""Add memory consolidation run audit table."""

from alembic import op
import sqlalchemy as sa

revision = "0010_memory_consolidation"
down_revision = "0009_memory_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_consolidation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("promoted_count", sa.Integer(), nullable=False),
        sa.Column("merged_count", sa.Integer(), nullable=False),
        sa.Column("superseded_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_consolidation_identity_created",
        "memory_consolidation_runs",
        ["identity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("memory_consolidation_runs")
