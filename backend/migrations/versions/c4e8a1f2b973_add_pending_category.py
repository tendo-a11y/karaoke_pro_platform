"""add orders pending category change fields

Revision ID: c4e8a1f2b973
Revises: a7c3e9d1f502

"""
import sqlalchemy as sa
from alembic import op


revision = 'c4e8a1f2b973'
down_revision = 'a7c3e9d1f502'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pending_service_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pending_category_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('pending_category_at')
        batch_op.drop_column('pending_service_id')
