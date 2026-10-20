"""add guest_accounts.trusted for auto-accept

Revision ID: e7b1c5d2a904
Revises: d6f2b9a4c183
"""
import sqlalchemy as sa
from alembic import op


revision = 'e7b1c5d2a904'
down_revision = 'd6f2b9a4c183'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('guest_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trusted', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('guest_accounts', schema=None) as batch_op:
        batch_op.drop_column('trusted')
