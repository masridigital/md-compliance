"""Add summary and evidence_data columns to risk_register.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _column_exists("risk_register", "summary"):
        op.add_column("risk_register", sa.Column("summary", sa.String(), nullable=True))

    if not _column_exists("risk_register", "evidence_data"):
        op.add_column("risk_register", sa.Column("evidence_data", sa.JSON(), server_default="[]", nullable=True))


def downgrade():
    op.drop_column("risk_register", "evidence_data")
    op.drop_column("risk_register", "summary")
