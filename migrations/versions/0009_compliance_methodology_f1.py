"""Phase F1 — compliance methodology schema.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-19

Adds the columns + tables introduced by METHODOLOGY.md Phase F1:

  project_evidence:
    + kind, status, source, integration_fingerprint,
      reviewed_by_id (FK users.id), reviewed_at, rejection_reason
  evidence_association:
    + requirement_slot
  controls:
    + evidence_requirements (JSON)
  project_subcontrols:
    + verified_at, verified_by_id (FK users.id), verification_note
  new table integration_facts
  new table ai_suggestions

All adds are guarded by _column_exists / _table_exists — rerunning is
a no-op.
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _inspector():
    from sqlalchemy import inspect
    return inspect(_bind())


def _column_exists(table, column):
    insp = _inspector()
    if table not in insp.get_table_names():
        return False
    return column in [c["name"] for c in insp.get_columns(table)]


def _table_exists(table):
    return table in _inspector().get_table_names()


def _add(table, column, coldef):
    if _column_exists(table, column):
        return
    op.add_column(table, sa.Column(column, *coldef[0], **coldef[1]))


def upgrade():
    # project_evidence — provenance + review state on every evidence row.
    _add("project_evidence", "kind",
         ((sa.String(),), {"nullable": False, "server_default": "uploaded"}))
    _add("project_evidence", "status",
         ((sa.String(),), {"nullable": False, "server_default": "draft"}))
    _add("project_evidence", "source",
         ((sa.String(),), {"nullable": True}))
    _add("project_evidence", "integration_fingerprint",
         ((sa.String(),), {"nullable": True}))
    _add("project_evidence", "reviewed_by_id",
         ((sa.String(), sa.ForeignKey("users.id")), {"nullable": True}))
    _add("project_evidence", "reviewed_at",
         ((sa.DateTime(),), {"nullable": True}))
    _add("project_evidence", "rejection_reason",
         ((sa.Text(),), {"nullable": True}))

    # evidence_association — which requirement slot this row satisfies.
    _add("evidence_association", "requirement_slot",
         ((sa.String(),), {"nullable": True}))

    # controls — framework requirement schema on the source control.
    _add("controls", "evidence_requirements",
         ((sa.JSON(),), {"nullable": True, "server_default": "{}"}))

    # project_subcontrols — human verification stamp.
    _add("project_subcontrols", "verified_at",
         ((sa.DateTime(),), {"nullable": True}))
    _add("project_subcontrols", "verified_by_id",
         ((sa.String(), sa.ForeignKey("users.id")), {"nullable": True}))
    _add("project_subcontrols", "verification_note",
         ((sa.Text(),), {"nullable": True}))

    # New tables ----------------------------------------------------------
    if not _table_exists("integration_facts"):
        op.create_table(
            "integration_facts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("assertion", sa.String(), nullable=False),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column("collected_at", sa.DateTime(), nullable=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_integration_facts_tenant_fingerprint",
            "integration_facts", ["tenant_id", "fingerprint"], unique=False,
        )

    if not _table_exists("ai_suggestions"):
        op.create_table(
            "ai_suggestions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("subject_type", sa.String(), nullable=False),
            sa.Column("subject_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(), nullable=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        )
        op.create_index(
            "ix_ai_suggestions_project_subject",
            "ai_suggestions", ["project_id", "subject_type", "subject_id"], unique=False,
        )

    # Backfill existing data to sensible defaults ------------------------
    # Rows predating F1 were created by evidence_generators.py +
    # llm_routes.py with group in ('auto_evidence','integration_scan').
    # Promote those to kind=llm_hint, status=proposed. Everything else
    # was human-uploaded and already treated as real evidence, so it
    # becomes kind=uploaded, status=accepted.
    op.execute(
        "UPDATE project_evidence "
        "SET kind = 'llm_hint', status = 'proposed' "
        "WHERE \"group\" IN ('auto_evidence', 'integration_scan') "
        "AND (kind IS NULL OR kind = 'uploaded')"
    )
    op.execute(
        "UPDATE project_evidence "
        "SET kind = 'uploaded', status = 'accepted' "
        "WHERE (\"group\" NOT IN ('auto_evidence', 'integration_scan') OR \"group\" IS NULL) "
        "AND (status IS NULL OR status = 'draft')"
    )


def downgrade():
    # Drop in reverse order. Tables first, then column adds.
    if _table_exists("ai_suggestions"):
        op.drop_index("ix_ai_suggestions_project_subject", table_name="ai_suggestions")
        op.drop_table("ai_suggestions")
    if _table_exists("integration_facts"):
        op.drop_index("ix_integration_facts_tenant_fingerprint", table_name="integration_facts")
        op.drop_table("integration_facts")

    for col in ("verification_note", "verified_by_id", "verified_at"):
        if _column_exists("project_subcontrols", col):
            op.drop_column("project_subcontrols", col)

    if _column_exists("controls", "evidence_requirements"):
        op.drop_column("controls", "evidence_requirements")

    if _column_exists("evidence_association", "requirement_slot"):
        op.drop_column("evidence_association", "requirement_slot")

    for col in ("rejection_reason", "reviewed_at", "reviewed_by_id",
                "integration_fingerprint", "source", "status", "kind"):
        if _column_exists("project_evidence", col):
            op.drop_column("project_evidence", col)
