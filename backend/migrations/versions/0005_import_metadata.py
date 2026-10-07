"""Public source links and field-level bibliographic provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0005_import_metadata'
down_revision = '0004_translation_cache'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('papers', sa.Column('source_url', sa.String(2048)))
    op.add_column('papers', sa.Column('metadata_sources_json', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('papers', sa.Column('metadata_warnings_json', sa.Text(), nullable=False, server_default='[]'))


def downgrade():
    with op.batch_alter_table('papers') as batch:
        batch.drop_column('metadata_warnings_json')
        batch.drop_column('metadata_sources_json')
        batch.drop_column('source_url')
