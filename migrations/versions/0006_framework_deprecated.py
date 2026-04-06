"""Add deprecated columns to frameworks table.

Revision ID: 0006_framework_deprecated
Revises: 0005_user_totp_timeout
Create Date: 2026-04-06

Changes:
  - Adds deprecated BOOLEAN column (default False)
  - Adds deprecated_message TEXT column (nullable)
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_framework_deprecated"
down_revision = "0005_user_totp_timeout"
branch_labels = None
depends_on = None


def _column_exists(table, column):
    """Check if a column already exists (idempotent migrations)."""
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _column_exists("frameworks", "deprecated"):
        op.add_column("frameworks", sa.Column("deprecated", sa.Boolean(), server_default="0", nullable=True))

    if not _column_exists("frameworks", "deprecated_message"):
        op.add_column("frameworks", sa.Column("deprecated_message", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("frameworks", "deprecated_message")
    op.drop_column("frameworks", "deprecated")
