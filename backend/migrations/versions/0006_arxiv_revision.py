"""Retain the observed arXiv PDF revision across future metadata refreshes."""
from alembic import op
import sqlalchemy as sa

revision = '0006_arxiv_revision'
down_revision = '0005_import_metadata'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('arxiv_version', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('papers') as batch:
        batch.drop_column('arxiv_version')
