"""Real PDF provenance, user notes, and full-text indexing."""

from alembic import op
import sqlalchemy as sa

revision = "0002_evidence_pdf"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

COLUMNS = {
    "papers": [
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=True),
    ],
    "paper_chunks": [
        sa.Column("bbox_json", sa.Text()),
        sa.Column("page_width", sa.Float()),
        sa.Column("page_height", sa.Float()),
    ],
    "evidence": [
        sa.Column("chunk_id", sa.String(64)),
        sa.Column("bbox_json", sa.Text()),
        sa.Column("page_width", sa.Float()),
        sa.Column("page_height", sa.Float()),
    ],
    "paper_analysis": [
        sa.Column("provider", sa.String(100), nullable=False, server_default="legacy"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="mock"),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
    ],
    "notes": [
        sa.Column("kind", sa.String(32), nullable=False, server_default="note"),
        sa.Column("source_text", sa.Text()),
        sa.Column("bbox_json", sa.Text()),
    ],
    "edges": [
        sa.Column(
            "relation_source", sa.String(32), nullable=False, server_default="legacy"
        )
    ],
}


def upgrade():
    connection = op.get_bind()
    for table, columns in COLUMNS.items():
        current = {
            column["name"] for column in sa.inspect(connection).get_columns(table)
        }
        for column in columns:
            if column.name not in current:
                op.add_column(table, column)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_papers_sha256 ON papers(sha256)")
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks_fts USING fts5(chunk_id UNINDEXED, paper_id UNINDEXED, content, tokenize='unicode61')"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON paper_chunks BEGIN INSERT INTO paper_chunks_fts(chunk_id,paper_id,content) VALUES(new.id,new.paper_id,new.content); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON paper_chunks BEGIN DELETE FROM paper_chunks_fts WHERE chunk_id=old.id; END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON paper_chunks BEGIN DELETE FROM paper_chunks_fts WHERE chunk_id=old.id; INSERT INTO paper_chunks_fts(chunk_id,paper_id,content) VALUES(new.id,new.paper_id,new.content); END"
    )
    op.execute("DELETE FROM paper_chunks_fts")
    op.execute(
        "INSERT INTO paper_chunks_fts(chunk_id,paper_id,content) SELECT id,paper_id,content FROM paper_chunks"
    )


def downgrade():
    for trigger in ("chunks_fts_insert", "chunks_fts_delete", "chunks_fts_update"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS paper_chunks_fts")
    op.execute("DROP INDEX IF EXISTS ix_papers_sha256")
    for table, columns in reversed(tuple(COLUMNS.items())):
        for column in reversed(columns):
            op.drop_column(table, column.name)
