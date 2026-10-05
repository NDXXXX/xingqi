"""Store the QQ sender ID allowed to use the local personal agent."""

from alembic import op
import sqlalchemy as sa


revision = "0014_qq_owner_user"
down_revision = "0013_memory_vaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel_configs") as batch:
        batch.add_column(sa.Column("owner_user_id", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("channel_configs") as batch:
        batch.drop_column("owner_user_id")
