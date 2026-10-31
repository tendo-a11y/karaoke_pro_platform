"""add clubs.group_approval_required (одобрение присаживания за групповой стол)

Revision ID: e5a7c9d1f2b4
Revises: d9f3b5a7c2e4
Create Date: 2026-10-31 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a7c9d1f2b4'
down_revision = 'd9f3b5a7c2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('group_approval_required', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('group_approval_required')
