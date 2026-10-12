"""add clubs.queue_round_since

Revision ID: d1f6b2c4e578
Revises: c9e5a1b3d467
Create Date: 2026-10-13 12:00:00.000000

Очередь по кругу: момент, когда KJ задал "Начало очереди" — спетые раньше
песни на положение круга не влияют.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1f6b2c4e578'
down_revision = 'c9e5a1b3d467'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clubs', sa.Column('queue_round_since', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('clubs', 'queue_round_since')
