"""club chat_auto_enabled

Revision ID: a7c3e9f2d5b1
Revises: e6a2c8d4b1f7
Create Date: 2026-11-11 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3e9f2d5b1"
down_revision = "e6a2c8d4b1f7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "clubs",
        sa.Column("chat_auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("clubs", "chat_auto_enabled")
