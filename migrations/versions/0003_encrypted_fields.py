"""Add settings_entra table for encrypted Entra ID credentials.

Revision ID: 0003_encrypted_fields
Revises: 0002_masri_additions
Create Date: 2026-03-23

Changes:
  - Adds ``settings_entra`` table with Fernet-encrypted credential columns.
  - No existing columns are modified — the EncryptedText TypeDecorator handles
    transparent encryption/decryption at the ORM layer for existing columns;
    no schema change is needed for them (the underlying DB type remains TEXT/VARCHAR).
  - Run ``python manage.py encrypt_existing`` after this migration to
    proactively re-encrypt any existing plaintext rows.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_encrypted_fields"
down_revision = "0002_masri_additions"
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    if not _table_exists("settings_entra"):
        op.create_table(
            "settings_entra",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(),
                sa.ForeignKey("tenants.id"),
                nullable=True,
            ),
            sa.Column("entra_tenant_id_enc", sa.Text(), nullable=True),
            sa.Column("entra_client_id_enc", sa.Text(), nullable=True),
            sa.Column("entra_client_secret_enc", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default="1"),
            sa.Column("date_added", sa.DateTime(), nullable=True),
            sa.Column("date_updated", sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table("settings_entra")
