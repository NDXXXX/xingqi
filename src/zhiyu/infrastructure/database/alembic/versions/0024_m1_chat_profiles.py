"""Persist selected conversation providers and complete character profiles."""

from alembic import op
import sqlalchemy as sa


revision = "0024_m1_chat_profiles"
down_revision = "0023_multi_agent"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("provider_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_provider_id_providers",
            "providers",
            ["provider_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("characters") as batch:
        batch.add_column(sa.Column("opening_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("world_setting", sa.Text(), nullable=True))
        batch.add_column(sa.Column("initial_scene", sa.Text(), nullable=True))
        batch.add_column(sa.Column("behavior_preferences", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("behavior_preferences")
        batch.drop_column("initial_scene")
        batch.drop_column("world_setting")
        batch.drop_column("opening_message")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_conversations_provider_id_providers", type_="foreignkey")
        batch.drop_column("provider_id")
