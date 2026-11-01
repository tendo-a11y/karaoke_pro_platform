"""add orders.is_karaoke (галочка «Караоке» при заказе по ссылке YouTube)

Revision ID: f6b8d2e4a1c3
Revises: e5a7c9d1f2b4
Create Date: 2026-11-01 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6b8d2e4a1c3'
down_revision = 'e5a7c9d1f2b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_karaoke', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('is_karaoke')
