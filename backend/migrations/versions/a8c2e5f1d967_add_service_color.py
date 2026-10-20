"""Цвет категории (текст в очереди и у гостя)

Revision ID: a8c2e5f1d967
Revises: f1a9d3c6e572
Create Date: 2026-10-20 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a8c2e5f1d967'
down_revision = 'f1a9d3c6e572'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('services') as batch_op:
        batch_op.add_column(sa.Column('color', sa.String(length=16), nullable=True))


def downgrade():
    with op.batch_alter_table('services') as batch_op:
        batch_op.drop_column('color')
