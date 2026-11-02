"""Checkpoint persistent paragraph translation without duplicating the cache."""
from alembic import op
import sqlalchemy as sa

revision = '0017_translation_queue'
down_revision = '0016_research_budget'
branch_labels = depends_on = None


def upgrade():
    op.create_table('translation_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('paper_id', sa.String(64), sa.ForeignKey('papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('profile_id', sa.String(100)), sa.Column('provider', sa.String(100), nullable=False),
        sa.Column('config_version', sa.String(64), nullable=False), sa.Column('prompt_version', sa.String(100), nullable=False),
        sa.Column('model_name', sa.String(200), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='queued'),
        sa.Column('reason', sa.String(64)), sa.Column('error', sa.Text()),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('usage_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_translation_jobs_paper_id', 'translation_jobs', ['paper_id'])
    op.create_index('ix_translation_jobs_status', 'translation_jobs', ['status'])
    op.create_table('translation_items',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('translation_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_item_id', sa.String(64), sa.ForeignKey('translation_items.id', ondelete='SET NULL')),
        sa.Column('paragraph_id', sa.String(64), nullable=False), sa.Column('original_paragraph_id', sa.String(64), nullable=False),
        sa.Column('aliases_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('refs_json', sa.Text(), nullable=False), sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False), sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('page', sa.Integer()), sa.Column('status', sa.String(24), nullable=False, server_default='queued'),
        sa.Column('phase', sa.String(24)), sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text()), sa.Column('translation_id', sa.String(64), sa.ForeignKey('translations.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_translation_items_job_id', 'translation_items', ['job_id'])
    op.create_index('ix_translation_items_work_item_id', 'translation_items', ['work_item_id'])


def downgrade():
    op.drop_table('translation_items')
    op.drop_table('translation_jobs')
