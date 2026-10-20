"""Следующий круг: галочка «пропустить круг» у заказа

Revision ID: f1a9d3c6e572
Revises: e7b1c5d2a904
Create Date: 2026-10-20 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a9d3c6e572'
down_revision = 'e7b1c5d2a904'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders') as batch_op:
        batch_op.add_column(
            sa.Column('skip_round', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table('orders') as batch_op:
        batch_op.drop_column('skip_round')
