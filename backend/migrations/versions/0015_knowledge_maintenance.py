"""Persistent knowledge-network maintenance runs and issues."""

from alembic import op
import sqlalchemy as sa


revision = "0015_knowledge_maintenance"
down_revision = "0014_research_findings"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "knowledge_maintenance_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("allow_external", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("safe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_maintenance_run_status_created",
        "knowledge_maintenance_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_knowledge_maintenance_runs_scope_id",
        "knowledge_maintenance_runs",
        ["scope_id"],
    )
    op.create_index(
        "ix_knowledge_maintenance_runs_source_fingerprint",
        "knowledge_maintenance_runs",
        ["source_fingerprint"],
    )
    op.create_table(
        "knowledge_maintenance_issues",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("knowledge_maintenance_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_basis_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("auto_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subject_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("external_leads_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("proposed_action_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("applied_change_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_maintenance_issue_run_status",
        "knowledge_maintenance_issues",
        ["run_id", "status"],
    )
    op.create_index(
        "ix_knowledge_maintenance_issue_source_fingerprint",
        "knowledge_maintenance_issues",
        ["source_fingerprint"],
    )


def downgrade():
    op.drop_index("ix_knowledge_maintenance_issue_source_fingerprint", table_name="knowledge_maintenance_issues")
    op.drop_index("ix_knowledge_maintenance_issue_run_status", table_name="knowledge_maintenance_issues")
    op.drop_table("knowledge_maintenance_issues")
    op.drop_index("ix_knowledge_maintenance_runs_source_fingerprint", table_name="knowledge_maintenance_runs")
    op.drop_index("ix_knowledge_maintenance_runs_scope_id", table_name="knowledge_maintenance_runs")
    op.drop_index("ix_knowledge_maintenance_run_status_created", table_name="knowledge_maintenance_runs")
    op.drop_table("knowledge_maintenance_runs")
