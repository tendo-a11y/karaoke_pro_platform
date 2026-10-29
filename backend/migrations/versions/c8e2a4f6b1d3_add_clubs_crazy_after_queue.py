"""add clubs.crazy_after_queue (крейзи-предложение после N песен в очереди)

Revision ID: c8e2a4f6b1d3
Revises: b7d1e2f3a4c5
Create Date: 2026-10-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8e2a4f6b1d3'
down_revision = 'b7d1e2f3a4c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('crazy_after_queue', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('crazy_after_queue')
