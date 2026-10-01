"""Persist recoverable memory extraction jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0008_memory_jobs"
down_revision = "0007_memory_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_message_id", name="uq_memory_jobs_user_message"),
    )
    op.create_index(
        "ix_memory_jobs_status_created", "memory_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("memory_jobs")
