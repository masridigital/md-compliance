"""Compliance platform schema — questionnaires, documents, templates.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-23

Adds the tables introduced by the compliance-platform spec:

  questionnaires          — per-tenant/per-framework answer sets
  exemption_profiles      — derived applicability decisions (NY DFS 500.19 etc.)
  compliance_documents    — generated/uploaded compliance artifacts
  compliance_doc_versions — version history with R2/storage-router key
  document_templates      — .docx templates with extracted placeholders

Section-level metadata (is_exemptable, applicable_exemptions, doc_types,
deadline_kind, severity) is stored under ``controls.meta`` — no schema
change needed.

All adds are guarded — rerunning is a no-op.
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _inspector():
    from sqlalchemy import inspect
    return inspect(op.get_bind())


def _table_exists(table):
    return table in _inspector().get_table_names()


def upgrade():
    if not _table_exists("questionnaires"):
        op.create_table(
            "questionnaires",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("framework_slug", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("answers", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_questionnaires_tenant_framework",
            "questionnaires",
            ["tenant_id", "framework_slug"],
            unique=False,
        )

    if not _table_exists("exemption_profiles"):
        op.create_table(
            "exemption_profiles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("framework_slug", sa.String(), nullable=False),
            sa.Column("questionnaire_id", sa.String(), sa.ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True),
            sa.Column("exemption_type", sa.String(), nullable=False, server_default="none"),  # none|limited|full
            sa.Column("exemptions_claimed", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("scope_waived", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("determined_at", sa.DateTime(), nullable=True),
            sa.Column("filed_at", sa.DateTime(), nullable=True),
            sa.Column("filing_confirmation", sa.String(), nullable=True),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_exemption_profiles_tenant_framework",
            "exemption_profiles",
            ["tenant_id", "framework_slug"],
            unique=True,
        )

    if not _table_exists("document_templates"):
        op.create_table(
            "document_templates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("framework_slug", sa.String(), nullable=True),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("storage_key", sa.String(), nullable=False),
            sa.Column("placeholders", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("placeholder_map", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_document_templates_tenant_doc_type",
            "document_templates",
            ["tenant_id", "doc_type"],
            unique=False,
        )

    if not _table_exists("compliance_documents"):
        op.create_table(
            "compliance_documents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("framework_slug", sa.String(), nullable=True),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("template_id", sa.String(), sa.ForeignKey("document_templates.id", ondelete="SET NULL"), nullable=True),
            sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_compliance_documents_tenant_doc_type",
            "compliance_documents",
            ["tenant_id", "doc_type"],
            unique=False,
        )

    if not _table_exists("compliance_doc_versions"):
        op.create_table(
            "compliance_doc_versions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("document_id", sa.String(), sa.ForeignKey("compliance_documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_num", sa.Integer(), nullable=False),
            sa.Column("storage_key", sa.String(), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("prompt_used", sa.Text(), nullable=True),
            sa.Column("generation_mode", sa.String(), nullable=True),  # from_scratch|from_template|uploaded
            sa.Column("generated_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("date_added", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_compliance_doc_versions_doc_version",
            "compliance_doc_versions",
            ["document_id", "version_num"],
            unique=True,
        )


def downgrade():
    for tbl, idx in [
        ("document_templates", "ix_document_templates_tenant_doc_type"),
        ("compliance_doc_versions", "ix_compliance_doc_versions_doc_version"),
        ("compliance_documents", "ix_compliance_documents_tenant_doc_type"),
        ("exemption_profiles", "ix_exemption_profiles_tenant_framework"),
        ("questionnaires", "ix_questionnaires_tenant_framework"),
    ]:
        if _table_exists(tbl):
            try:
                op.drop_index(idx, table_name=tbl)
            except Exception:
                pass
            op.drop_table(tbl)
