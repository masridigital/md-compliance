"""Add title_hash to risk_register and swap UniqueConstraint for encrypted title.

Revision ID: 0004_risk_title_hash
Revises: 0003_encrypted_fields
Create Date: 2026-03-23

Changes:
  - Adds title_hash VARCHAR(64) column to risk_register.
  - Drops the old UniqueConstraint on (title, tenant_id).
  - Adds new UniqueConstraint on (title_hash, tenant_id).
  - Back-fills title_hash for existing rows using SHA-256(title|tenant_id).
  - The title column itself remains VARCHAR so pre-existing plaintext rows
    continue to be read by EncryptedText (legacy fallback).  They will be
    re-encrypted automatically on next write, or you can run:
        python manage.py encrypt_existing
"""

import hashlib
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


revision = "0004_risk_title_hash"
down_revision = "0003_encrypted_fields"
branch_labels = None
depends_on = None


def _table_exists(table_name):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def upgrade():
    if not _table_exists("risk_register"):
        return  # fresh install — table created by SQLAlchemy with correct schema

    bind = op.get_bind()

    # 1. Add title_hash column (nullable so back-fill can run first)
    if not _column_exists("risk_register", "title_hash"):
        op.add_column("risk_register", sa.Column("title_hash", sa.String(64), nullable=True))

    # 2. Back-fill title_hash for existing rows
    rows = bind.execute(text("SELECT id, title, tenant_id FROM risk_register")).fetchall()
    for row in rows:
        title = row[1] or ""
        tenant_id = row[2] or ""
        h = hashlib.sha256(f"{title.lower()}|{tenant_id}".encode()).hexdigest()
        bind.execute(
            text("UPDATE risk_register SET title_hash = :h WHERE id = :id"),
            {"h": h, "id": row[0]},
        )

    # 3. Drop the old plaintext unique constraint (best-effort — name varies by DB)
    try:
        op.drop_constraint("risk_register_title_tenant_id_key", "risk_register", type_="unique")
    except Exception:
        pass  # constraint may have a different name or not exist
    try:
        op.drop_constraint("uq_risk_register_title_tenant", "risk_register", type_="unique")
    except Exception:
        pass

    # 4. Add new uniqueness constraint on hash column
    try:
        op.create_unique_constraint(
            "uq_risk_title_hash_tenant",
            "risk_register",
            ["title_hash", "tenant_id"],
        )
    except Exception:
        pass  # may already exist on fresh installs


def downgrade():
    try:
        op.drop_constraint("uq_risk_title_hash_tenant", "risk_register", type_="unique")
    except Exception:
        pass
    try:
        op.create_unique_constraint(
            "risk_register_title_tenant_id_key",
            "risk_register",
            ["title", "tenant_id"],
        )
    except Exception:
        pass
    try:
        op.drop_column("risk_register", "title_hash")
    except Exception:
        pass
