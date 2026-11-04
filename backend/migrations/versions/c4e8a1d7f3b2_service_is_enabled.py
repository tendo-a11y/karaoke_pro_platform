"""service is_enabled; drop club section flags

Revision ID: c4e8a1d7f3b2
Revises: b9d2f4a6c8e1
Create Date: 2026-11-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "c4e8a1d7f3b2"
down_revision = "b9d2f4a6c8e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("services", sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.drop_column("clubs", "guest_extra_categories_visible")
    op.drop_column("clubs", "guest_main_categories_visible")


def downgrade():
    op.add_column("clubs", sa.Column("guest_main_categories_visible", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("clubs", sa.Column("guest_extra_categories_visible", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.drop_column("services", "is_enabled")
