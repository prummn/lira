"""Finite research findings and locally scheduled review questions."""
from alembic import op
import sqlalchemy as sa

revision = '0014_research_findings'
down_revision = '0013_background_research'
branch_labels = depends_on = None


def upgrade():
    op.add_column('research_tasks', sa.Column('kind', sa.String(24), nullable=False, server_default='essay'))
    op.add_column('research_scopes', sa.Column('work_types_json', sa.Text(), nullable=False, server_default='["essay"]'))
    op.create_table('research_findings',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('collection_id', sa.String(64), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('identity', sa.String(64), nullable=False), sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('title', sa.Text(), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('next_step', sa.Text(), nullable=False), sa.Column('sources_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('review_count', sa.Integer(), nullable=False),
        sa.Column('due_at', sa.DateTime()), sa.Column('model', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('collection_id', 'identity', name='uq_research_finding_identity'))
    op.create_index('ix_research_findings_collection_id', 'research_findings', ['collection_id'])
    op.create_table('research_finding_revisions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('finding_id', sa.String(64), sa.ForeignKey('research_findings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.String(64), sa.ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False), sa.Column('content_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_research_finding_revisions_finding_id', 'research_finding_revisions', ['finding_id'])


def downgrade():
    op.drop_table('research_finding_revisions')
    op.drop_table('research_findings')
    op.drop_column('research_scopes', 'work_types_json')
    op.drop_column('research_tasks', 'kind')
