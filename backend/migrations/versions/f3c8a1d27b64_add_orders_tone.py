"""add orders tone

Revision ID: f3c8a1d27b64
Revises: e7b1c3d5a9f2
Create Date: 2026-10-08 00:00:00.000000

Тональность, которую гость выбирает при заказе песни (от -6 до +6).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3c8a1d27b64'
down_revision = 'e7b1c3d5a9f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tone', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('tone')
