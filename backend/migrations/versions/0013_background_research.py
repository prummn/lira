"""Durable collection essays, finite jobs and opt-in policy."""
from alembic import op
import sqlalchemy as sa

revision = '0013_background_research'
down_revision = '0012_knowledge_curation'
branch_labels = depends_on = None


def upgrade():
    op.create_table('research_control', sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('settings_json', sa.Text(), nullable=False))
    op.create_table('research_scopes',
        sa.Column('collection_id', sa.String(64), sa.ForeignKey('collections.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('focus', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_table('research_tasks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('collection_id', sa.String(64), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('stage', sa.String(24), nullable=False), sa.Column('material_json', sa.Text(), nullable=False),
        sa.Column('checkpoint_json', sa.Text(), nullable=False), sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False), sa.Column('usage_json', sa.Text(), nullable=False),
        sa.Column('error', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('collection_id', 'fingerprint', name='uq_research_material'))
    op.create_index('ix_research_tasks_collection_id', 'research_tasks', ['collection_id'])
    op.create_table('research_revisions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('collection_id', sa.String(64), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.String(64), sa.ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('number', sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Text(), nullable=False) for name in ('title', 'dek', 'markdown', 'changes', 'sources_json', 'coverage_json')],
        sa.Column('model', sa.String(200), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('collection_id', 'number', name='uq_research_revision'))
    op.create_index('ix_research_revisions_collection_id', 'research_revisions', ['collection_id'])


def downgrade():
    for table in ('research_revisions', 'research_tasks', 'research_scopes', 'research_control'):
        op.drop_table(table)
