"""add clubs evening_closed_at

Revision ID: b7e3f1a9c2d4
Revises: a4d9e2b61c77
Create Date: 2026-10-09 01:00:00.000000

Когда в последний раз был закрыт вечер ("Закрыть все столы" вручную или
автоматически) — всё, что было до этого, относится к прошлому вечеру.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e3f1a9c2d4'
down_revision = 'a4d9e2b61c77'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evening_closed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('evening_closed_at')
