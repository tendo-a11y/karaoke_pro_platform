"""add new_songs

Revision ID: c5a8d3e7f912
Revises: b7e3f1a9c2d4
Create Date: 2026-10-09 02:00:00.000000

"Новинки" — песни, отмеченные KJ галочкой в живой очереди.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5a8d3e7f912'
down_revision = 'b7e3f1a9c2d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'new_songs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('song_title', sa.String(length=500), nullable=False),
        sa.Column('artist', sa.String(length=500), nullable=True),
        sa.Column('norm_key', sa.String(length=1100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('club_id', 'norm_key', name='uq_new_songs_club_key'),
    )
    with op.batch_alter_table('new_songs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_new_songs_club_id'), ['club_id'], unique=False)


def downgrade():
    with op.batch_alter_table('new_songs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_new_songs_club_id'))
    op.drop_table('new_songs')
