"""Add LLM client credentials and Entra multi_tenant flag

Revision ID: 0005_llm_client_creds_entra_multitenant
Revises: 0004_risk_title_hash
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_llm_client_creds_entra_multitenant"
down_revision = "0004_risk_title_hash"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("settings_llm") as batch_op:
        batch_op.add_column(sa.Column("llm_client_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("llm_client_secret_enc", sa.Text(), nullable=True))

    with op.batch_alter_table("settings_entra") as batch_op:
        batch_op.add_column(sa.Column("multi_tenant", sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("settings_entra") as batch_op:
        batch_op.drop_column("multi_tenant")

    with op.batch_alter_table("settings_llm") as batch_op:
        batch_op.drop_column("llm_client_secret_enc")
        batch_op.drop_column("llm_client_id")
