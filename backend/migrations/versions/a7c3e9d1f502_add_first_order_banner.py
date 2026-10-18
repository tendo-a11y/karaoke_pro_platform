"""add clubs first order banner settings

Revision ID: a7c3e9d1f502
Revises: d5a1c8e7b921

"""
import sqlalchemy as sa
from alembic import op


revision = 'a7c3e9d1f502'
down_revision = 'd5a1c8e7b921'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('first_order_banner_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
        batch_op.add_column(sa.Column('first_order_banner_text', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('first_order_banner_text')
        batch_op.drop_column('first_order_banner_enabled')
