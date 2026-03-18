"""Initial schema — baseline gapps tables

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-17

This migration captures the original gapps table set as-is.
It will be skipped on existing databases via the stamp_if_exists
logic in run.sh (existing tables are detected and the migration
history is stamped to head without re-running DDL).
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # NOTE: These tables already exist on installations that were originally
    # set up with `init_db`. The run.sh startup script detects existing tables
    # and stamps migration history to head, so this upgrade() is only executed
    # on a completely fresh (empty) database.

    op.create_table(
        "tenant",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "user",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), server_default="user"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # Additional gapps tables are created by init_db on fresh installs.
    # On existing databases this migration is never executed (stamped to head).


def downgrade():
    op.drop_table("user")
    op.drop_table("tenant")
