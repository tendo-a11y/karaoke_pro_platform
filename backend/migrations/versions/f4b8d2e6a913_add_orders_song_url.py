"""add orders.song_url

Revision ID: f4b8d2e6a913
Revises: e2a7c4f9b153
Create Date: 2026-10-09 14:00:00.000000

Ссылка YouTube, по которой гость нашёл песню — KJ открывает её после "Принять".
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4b8d2e6a913'
down_revision = 'e2a7c4f9b153'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('song_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('song_url')
