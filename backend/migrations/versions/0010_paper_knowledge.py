"""Evidence-backed paper knowledge candidates and canonical field entities."""
from alembic import op
import sqlalchemy as sa

revision = '0010_paper_knowledge'
down_revision = '0009_research_activity'
branch_labels = depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('knowledge_status', sa.String(32), nullable=False, server_default='unread'))
    op.create_table(
        'knowledge_entities',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('normalized_name', sa.String(300), nullable=False),
        sa.Column('aliases_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('description', sa.Text()),
        sa.Column('status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('entity_type', 'normalized_name', name='uq_knowledge_entity_name'),
    )
    op.create_index('ix_knowledge_entities_entity_type', 'knowledge_entities', ['entity_type'])
    op.create_index('ix_knowledge_entities_normalized_name', 'knowledge_entities', ['normalized_name'])
    op.create_index('ix_knowledge_entities_status', 'knowledge_entities', ['status'])
    op.create_table(
        'knowledge_candidates',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('paper_id', sa.String(64), sa.ForeignKey('papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_id', sa.String(64), sa.ForeignKey('knowledge_entities.id', ondelete='SET NULL')),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('normalized_name', sa.String(300), nullable=False),
        sa.Column('aliases_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('description', sa.Text()),
        sa.Column('role', sa.String(32), nullable=False, server_default='cited'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('status', sa.String(32), nullable=False, server_default='candidate'),
        sa.Column('evidence_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('run_id', sa.String(100)),
        sa.Column('model_version', sa.String(200)),
        sa.Column('prompt_version', sa.String(100)),
        sa.Column('conflict_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_knowledge_candidates_paper_id', 'knowledge_candidates', ['paper_id'])
    op.create_index('ix_knowledge_candidates_entity_id', 'knowledge_candidates', ['entity_id'])
    op.create_index('ix_knowledge_candidates_paper_status', 'knowledge_candidates', ['paper_id', 'status'])
    op.create_index('ix_knowledge_candidates_normalized', 'knowledge_candidates', ['entity_type', 'normalized_name'])
    op.create_index('ix_knowledge_candidates_run_id', 'knowledge_candidates', ['run_id'])
    op.create_index('ix_knowledge_candidates_status', 'knowledge_candidates', ['status'])
    op.create_table(
        'knowledge_relations',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('paper_id', sa.String(64), sa.ForeignKey('papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relation', sa.String(48), nullable=False),
        sa.Column('source_name', sa.String(300), nullable=False),
        sa.Column('source_normalized_name', sa.String(300), nullable=False),
        sa.Column('target_name', sa.String(300), nullable=False),
        sa.Column('target_normalized_name', sa.String(300), nullable=False),
        sa.Column('source_candidate_id', sa.String(64), sa.ForeignKey('knowledge_candidates.id', ondelete='SET NULL')),
        sa.Column('target_candidate_id', sa.String(64), sa.ForeignKey('knowledge_candidates.id', ondelete='SET NULL')),
        sa.Column('description', sa.Text()),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('status', sa.String(32), nullable=False, server_default='candidate'),
        sa.Column('evidence_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('run_id', sa.String(100)),
        sa.Column('model_version', sa.String(200)),
        sa.Column('prompt_version', sa.String(100)),
        sa.Column('conflict_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_knowledge_relations_paper_id', 'knowledge_relations', ['paper_id'])
    op.create_index('ix_knowledge_relations_source_candidate_id', 'knowledge_relations', ['source_candidate_id'])
    op.create_index('ix_knowledge_relations_target_candidate_id', 'knowledge_relations', ['target_candidate_id'])
    op.create_index('ix_knowledge_relations_paper_status', 'knowledge_relations', ['paper_id', 'status'])
    op.create_index('ix_knowledge_relations_run_id', 'knowledge_relations', ['run_id'])
    op.create_index('ix_knowledge_relations_status', 'knowledge_relations', ['status'])


def downgrade():
    op.drop_table('knowledge_relations')
    op.drop_table('knowledge_candidates')
    op.drop_table('knowledge_entities')
