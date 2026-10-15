"""Preserve exact line regions and page geometry for reading annotations."""
from alembic import op
import sqlalchemy as sa

revision = '0008_note_anchors'
down_revision = '0007_intelligence'
branch_labels = depends_on = None


def upgrade():
    op.add_column('notes', sa.Column('anchors_json', sa.Text(), nullable=False, server_default='[]'))


def downgrade():
    with op.batch_alter_table('notes') as table:
        table.drop_column('anchors_json')
