"""add guest section visibility flags to clubs

Revision ID: b9d2f4a6c8e1
Revises: a7c3e9f1b2d4
Create Date: 2026-11-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "b9d2f4a6c8e1"
down_revision = "a7c3e9f1b2d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clubs", sa.Column("guest_main_categories_visible", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("clubs", sa.Column("guest_extra_categories_visible", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("clubs", "guest_extra_categories_visible")
    op.drop_column("clubs", "guest_main_categories_visible")
