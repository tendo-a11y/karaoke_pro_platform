"""add guest_kj_names table

Revision ID: a7c3e9f1b2d4
Revises: f6b8d2e4a1c3
Create Date: 2026-11-03 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3e9f1b2d4"
down_revision = "f6b8d2e4a1c3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guest_kj_names",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.club_id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kj_name", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("club_id", "telegram_user_id", name="uq_guest_kj_names_club_guest"),
    )
    op.create_index("ix_guest_kj_names_club_id", "guest_kj_names", ["club_id"])


def downgrade():
    op.drop_index("ix_guest_kj_names_club_id", table_name="guest_kj_names")
    op.drop_table("guest_kj_names")
