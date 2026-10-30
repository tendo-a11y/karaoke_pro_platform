"""add clubs.standard_messages (дежурные сообщения KJ гостям)

Revision ID: d9f3b5a7c2e4
Revises: c8e2a4f6b1d3
Create Date: 2026-10-30 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd9f3b5a7c2e4'
down_revision = 'c8e2a4f6b1d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('standard_messages', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('standard_messages')
