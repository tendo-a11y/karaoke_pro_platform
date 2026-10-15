"""add clubs.guest_queue_visible (показывать очередь гостям)

Revision ID: b7f3e9a1c502
Revises: a6e2d9f4c713
Create Date: 2026-10-15 12:00:00.000000

KJ переключает видимость живой очереди для гостей. По умолчанию — видна.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f3e9a1c502'
down_revision = 'a6e2d9f4c713'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clubs', sa.Column('guest_queue_visible', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('clubs', 'guest_queue_visible')
