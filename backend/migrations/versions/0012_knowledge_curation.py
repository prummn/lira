"""Maintain canonical objects and retain manual curation history."""
from alembic import op
import sqlalchemy as sa

revision = '0012_knowledge_curation'
down_revision = '0011_conversations'
branch_labels = depends_on = None


def upgrade():
    op.add_column('knowledge_entities', sa.Column('links_json', sa.Text(), nullable=False, server_default='[]'))
    # SQLite supports an inline reference on an added nullable column.
    if op.get_bind().dialect.name == 'sqlite':
        op.execute('ALTER TABLE knowledge_entities ADD COLUMN merged_into_id VARCHAR(64) REFERENCES knowledge_entities(id)')
    else:
        op.add_column('knowledge_entities', sa.Column('merged_into_id', sa.String(64), sa.ForeignKey('knowledge_entities.id')))
    op.create_table('knowledge_changes',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('subject_type', sa.String(16), nullable=False),
        sa.Column('subject_id', sa.String(64), nullable=False),
        sa.Column('action', sa.String(48), nullable=False),
        sa.Column('before_json', sa.Text(), nullable=False),
        sa.Column('after_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_knowledge_changes_subject_id', 'knowledge_changes', ['subject_id'])


def downgrade():
    op.drop_table('knowledge_changes')
    with op.batch_alter_table('knowledge_entities') as batch:
        batch.drop_column('merged_into_id')
        batch.drop_column('links_json')
