"""add orders guest_song_text

Revision ID: e7b1c3d5a9f2
Revises: d2a9f6c381be
Create Date: 2026-10-07 00:00:00.000000

То, что гость написал при заказе, до того как KJ исправил название песни
на точное из VirtualDJ (запрос пользователя 2026-10: заказ "cvecha" и
песня "Свеча" в очереди VirtualDJ должны сливаться в одну строку).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b1c3d5a9f2'
down_revision = 'd2a9f6c381be'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('guest_song_text', sa.String(length=1000), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('guest_song_text')
