"""Add TOTP 2FA and session timeout columns to users table.

Revision ID: 0005_user_totp_timeout
Revises: 0004_risk_title_hash
Create Date: 2026-03-30

Changes:
  - Adds totp_secret_enc TEXT column (Fernet-encrypted TOTP secret)
  - Adds totp_enabled BOOLEAN column (default False)
  - Adds session_timeout_minutes INTEGER column (per-user override, nullable)
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_user_totp_timeout"
down_revision = "0004_risk_title_hash"
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
    if not _column_exists("users", "totp_secret_enc"):
        op.add_column("users", sa.Column("totp_secret_enc", sa.Text(), nullable=True))

    if not _column_exists("users", "totp_enabled"):
        op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), server_default="0", nullable=True))

    if not _column_exists("users", "session_timeout_minutes"):
        op.add_column("users", sa.Column("session_timeout_minutes", sa.Integer(), nullable=True))


def downgrade():
    if _column_exists("users", "session_timeout_minutes"):
        op.drop_column("users", "session_timeout_minutes")
    if _column_exists("users", "totp_enabled"):
        op.drop_column("users", "totp_enabled")
    if _column_exists("users", "totp_secret_enc"):
        op.drop_column("users", "totp_secret_enc")
