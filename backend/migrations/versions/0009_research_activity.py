"""Daily local research activity aggregates for the library heatmap."""

from alembic import op
import sqlalchemy as sa

revision = "0009_research_activity"
down_revision = "0008_note_anchors"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "research_activity",
        sa.Column("day", sa.Date(), primary_key=True, nullable=False),
        sa.Column("reading", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imports", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paper_ids_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_table("research_activity")
