"""add orders settled_at for partial table close

Revision ID: d6f2b9a4c183
Revises: c4e8a1f2b973

"""
import sqlalchemy as sa
from alembic import op


revision = 'd6f2b9a4c183'
down_revision = 'c4e8a1f2b973'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('settled_at')
