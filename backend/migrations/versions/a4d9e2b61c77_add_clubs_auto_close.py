"""add clubs auto close

Revision ID: a4d9e2b61c77
Revises: f3c8a1d27b64
Create Date: 2026-10-09 00:00:00.000000

Автозакрытие столов в заданное время (см. services/auto_close_service.py).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4d9e2b61c77'
down_revision = 'f3c8a1d27b64'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_close_enabled', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('auto_close_time', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('auto_close_tz_offset', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('auto_close_last_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('auto_close_last_date')
        batch_op.drop_column('auto_close_tz_offset')
        batch_op.drop_column('auto_close_time')
        batch_op.drop_column('auto_close_enabled')
