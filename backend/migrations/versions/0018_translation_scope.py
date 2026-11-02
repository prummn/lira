"""Record the body-only scope used by full translation jobs."""
from alembic import op
import sqlalchemy as sa

revision = '0018_translation_scope'
down_revision = '0017_translation_queue'
branch_labels = depends_on = None


def upgrade():
    op.add_column('translation_jobs', sa.Column('scope_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('translation_jobs', sa.Column('scope_skipped', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('translation_jobs', sa.Column('scope_reason', sa.String(64)))


def downgrade():
    op.drop_column('translation_jobs', 'scope_reason')
    op.drop_column('translation_jobs', 'scope_skipped')
    op.drop_column('translation_jobs', 'scope_total')
