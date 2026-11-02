"""Durable research conversations and answer/source snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0011_conversations'
down_revision = '0010_paper_knowledge'
branch_labels = depends_on = None


def upgrade():
    op.create_table('chat_conversations',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('paper_id', sa.String(64), sa.ForeignKey('papers.id', ondelete='CASCADE')),
        sa.Column('context_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('context_key', sa.String(64), nullable=False),
        sa.Column('title', sa.String(200), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    for column in ('kind', 'paper_id', 'context_key'):
        op.create_index('ix_chat_conversations_' + column, 'chat_conversations', [column])
    op.create_table('chat_turns',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('conversation_id', sa.String(64), sa.ForeignKey('chat_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', sa.String(64), unique=True, nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='running'),
        sa.Column('response_json', sa.Text()), sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_chat_turns_conversation_id', 'chat_turns', ['conversation_id'])
    op.create_index('uq_chat_running', 'chat_turns', ['conversation_id'], unique=True, sqlite_where=sa.text("status = 'running'"))


def downgrade():
    op.drop_table('chat_turns')
    op.drop_table('chat_conversations')
