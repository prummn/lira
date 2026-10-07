"""Structured evidence-backed Paper Card and model/prompt provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0003_paper_card'
down_revision = '0002_evidence_pdf'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('paper_analysis',sa.Column('card_json',sa.Text(),nullable=False,server_default='{}'))
    op.add_column('paper_analysis',sa.Column('model_version',sa.String(200)))
    op.add_column('paper_analysis',sa.Column('prompt_version',sa.String(100)))


def downgrade():
    with op.batch_alter_table('paper_analysis') as batch:
        batch.drop_column('prompt_version')
        batch.drop_column('model_version')
        batch.drop_column('card_json')
