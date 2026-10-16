"""add orders.priority_slot and orders.priority_requested (приоритет песни за столом)

Revision ID: d5a1c8e7b921
Revises: b7f3e9a1c502
Create Date: 2026-10-16 12:00:00.000000

KJ ставит песню на место 1 или 2 за столом; гость может попросить приоритет,
и заявка ждёт подтверждения KJ.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5a1c8e7b921'
down_revision = 'b7f3e9a1c502'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orders', sa.Column('priority_slot', sa.SmallInteger(), nullable=True))
    op.add_column('orders', sa.Column('priority_requested', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('orders', 'priority_requested')
    op.drop_column('orders', 'priority_slot')
