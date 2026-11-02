"""Persist observed account budget independently of editable research settings."""
from alembic import op
import sqlalchemy as sa

revision = '0016_research_budget'
down_revision = '0015_knowledge_maintenance'
branch_labels = depends_on = None


def upgrade():
    op.add_column('research_control', sa.Column('budget_json', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('research_tasks', sa.Column('intent_key', sa.String(64)))
    op.create_index('ix_research_tasks_intent_key', 'research_tasks', ['intent_key'])


def downgrade():
    op.drop_index('ix_research_tasks_intent_key', 'research_tasks')
    op.drop_column('research_tasks', 'intent_key')
    op.drop_column('research_control', 'budget_json')
