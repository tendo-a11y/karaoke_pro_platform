"""club extra_categories_reset_day

Revision ID: e6a2c8d4b1f7
Revises: d5f1a9c3e7b8
Create Date: 2026-11-05 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "e6a2c8d4b1f7"
down_revision = "d5f1a9c3e7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clubs", sa.Column("extra_categories_reset_day", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("clubs", "extra_categories_reset_day")
