"""Add a rebuildable FTS5 index for Markdown-derived memory text."""

from alembic import op


revision = "0021_memory_fts"
down_revision = "0020_memory_context_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE memories SET trust = 'imported' "
        "WHERE source_kind = 'import' AND source_message_id IS NULL"
    )
    op.execute(
        "CREATE VIRTUAL TABLE memory_fts USING "
        "fts5(memory_id UNINDEXED, content, tokenize='trigram')"
    )
    op.execute(
        "INSERT INTO memory_fts(rowid, memory_id, content) "
        "SELECT rowid, id, content FROM memories"
    )
    op.execute(
        "CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN "
        "INSERT INTO memory_fts(rowid, memory_id, content) "
        "VALUES (new.rowid, new.id, new.content); END"
    )
    op.execute(
        "CREATE TRIGGER memories_fts_update AFTER UPDATE OF content ON memories BEGIN "
        "DELETE FROM memory_fts WHERE rowid = old.rowid; "
        "INSERT INTO memory_fts(rowid, memory_id, content) "
        "VALUES (new.rowid, new.id, new.content); END"
    )
    op.execute(
        "CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN "
        "DELETE FROM memory_fts WHERE rowid = old.rowid; END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER memories_fts_delete")
    op.execute("DROP TRIGGER memories_fts_update")
    op.execute("DROP TRIGGER memories_fts_insert")
    op.execute("DROP TABLE memory_fts")
