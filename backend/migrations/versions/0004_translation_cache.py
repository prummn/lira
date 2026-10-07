"""Persistent paragraph translations with source and model provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0004_translation_cache"
down_revision = "0003_paper_card"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "translations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.String(64), sa.ForeignKey("paper_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(200)),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chunk_id", "source_hash", "provider", "config_version", "prompt_version", name="uq_translation_cache"),
    )
    op.create_index("ix_translations_paper_id", "translations", ["paper_id"])
    op.create_index("ix_translations_chunk_id", "translations", ["chunk_id"])


def downgrade():
    op.drop_table("translations")
