"""add song_list_hidden

Revision ID: d9f4b2c6e831
Revises: c5a8d3e7f912
Create Date: 2026-10-09 03:00:00.000000

KJ скрывает песни из списков гостя ("Популярные", "История за час").
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9f4b2c6e831'
down_revision = 'c5a8d3e7f912'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'song_list_hidden',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('norm_key', sa.String(length=1100), nullable=True),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('song_title', sa.String(length=500), nullable=True),
        sa.Column('artist', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('song_list_hidden', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_song_list_hidden_club_id'), ['club_id'], unique=False)


def downgrade():
    with op.batch_alter_table('song_list_hidden', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_song_list_hidden_club_id'))
    op.drop_table('song_list_hidden')
