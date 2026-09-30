"""Add provider metadata, model limits and application settings."""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase12"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE providers SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE providers SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

    with op.batch_alter_table("providers") as batch:
        batch.alter_column("created_at", nullable=False)
        batch.alter_column("updated_at", nullable=False)
        batch.create_unique_constraint("uq_providers_name", ["name"])

    with op.batch_alter_table("model_configs") as batch:
        batch.add_column(sa.Column("context_window", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_output_tokens", sa.Integer(), nullable=True))

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    with op.batch_alter_table("model_configs") as batch:
        batch.drop_column("max_output_tokens")
        batch.drop_column("context_window")
    with op.batch_alter_table("providers") as batch:
        batch.drop_constraint("uq_providers_name", type_="unique")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
