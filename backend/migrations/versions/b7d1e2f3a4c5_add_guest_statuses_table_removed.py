"""add guest_statuses.table_removed_at (плашка "Вы сняты со стола" при входе)

Revision ID: b7d1e2f3a4c5
Revises: a6c3e9f1d2b7
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d1e2f3a4c5'
down_revision = 'a6c3e9f1d2b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('guest_statuses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('table_removed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('guest_statuses', schema=None) as batch_op:
        batch_op.drop_column('table_removed_at')
