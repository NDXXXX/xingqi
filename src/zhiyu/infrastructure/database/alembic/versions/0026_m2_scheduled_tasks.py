"""Add one-time local and QQ reminder tasks."""

from alembic import op
import sqlalchemy as sa


revision = "0026_m2_scheduled_tasks"
down_revision = "0025_m2_shared_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="local"),
        sa.Column("channel_config_id", sa.String(36), sa.ForeignKey("channel_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_user_id", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scheduled_tasks_due_at", "scheduled_tasks", ["due_at"])
    op.create_index("ix_scheduled_tasks_due", "scheduled_tasks", ["status", "enabled", "next_attempt_at"])


def downgrade():
    op.drop_index("ix_scheduled_tasks_due", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_due_at", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
