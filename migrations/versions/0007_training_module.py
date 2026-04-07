"""Add training and training_assignment tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "training",
        sa.Column("id", sa.String(8), primary_key=True),
        sa.Column("tenant_id", sa.String(8), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("content_type", sa.String(50), server_default="document"),
        sa.Column("content_url", sa.Text()),
        sa.Column("frequency", sa.String(50), server_default="annual"),
        sa.Column("framework_requirements", sa.JSON(), server_default="[]"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("date_added", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("date_updated", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "training_assignment",
        sa.Column("id", sa.String(8), primary_key=True),
        sa.Column("tenant_id", sa.String(8), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("training_id", sa.String(8), sa.ForeignKey("training.id"), nullable=False, index=True),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("user_name", sa.String(255)),
        sa.Column("assigned_date", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("due_date", sa.DateTime()),
        sa.Column("completed_date", sa.DateTime()),
        sa.Column("score", sa.Integer()),
        sa.Column("certificate_url", sa.Text()),
        sa.Column("reminder_sent", sa.Boolean(), server_default="false"),
        sa.Column("date_added", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("date_updated", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("training_assignment")
    op.drop_table("training")
