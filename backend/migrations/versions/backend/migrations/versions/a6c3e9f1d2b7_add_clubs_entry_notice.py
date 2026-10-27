"""add clubs.entry_notice (плашка на экране входа гостя, меняется в KJ)

Revision ID: a6c3e9f1d2b7
Revises: d2f8a6b1c904
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'a6c3e9f1d2b7'
down_revision = 'd2f8a6b1c904'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entry_notice', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('entry_notice')
