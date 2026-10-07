"""Persistent staged analysis and credential-free model cache."""
from alembic import op
import sqlalchemy as sa

revision = '0007_intelligence'
down_revision = '0006_arxiv_revision'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('intelligence_status', sa.String(32), nullable=False, server_default='unanalyzed'))
    op.add_column('papers', sa.Column('intelligence_report_json', sa.Text(), nullable=True))
    op.add_column('papers', sa.Column('intelligence_analyzed_at', sa.DateTime(), nullable=True))
    # Previous remote cards used a truncated context; do not label them as full-paper complete.
    op.execute(sa.text("UPDATE papers SET intelligence_status='partial', intelligence_report_json=:report WHERE id IN (SELECT paper_id FROM paper_analysis WHERE mode='remote')").bindparams(report='{"legacy":true,"coverage":{"complete":false}}'))
    op.create_table('intelligence_tasks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('paper_id', sa.String(64), sa.ForeignKey('papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('phase', sa.String(64), nullable=False),
        sa.Column('run_token', sa.String(32)),
        sa.Column('completed_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('report_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_intelligence_tasks_paper_id', 'intelligence_tasks', ['paper_id'])
    op.create_index('uq_intelligence_active_paper', 'intelligence_tasks', ['paper_id'], unique=True, sqlite_where=sa.text("status IN ('queued','running')"))
    op.create_table('model_call_cache',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('operation', sa.String(100), nullable=False),
        sa.Column('response_json', sa.Text(), nullable=False),
        sa.Column('usage_json', sa.Text(), nullable=False),
        sa.Column('model', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('model_call_cache')
    op.drop_table('intelligence_tasks')
    with op.batch_alter_table('papers') as batch:
        batch.drop_column('intelligence_analyzed_at')
        batch.drop_column('intelligence_report_json')
        batch.drop_column('intelligence_status')
