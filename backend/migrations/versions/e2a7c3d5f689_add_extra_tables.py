"""add extra_tables

Revision ID: e2a7c3d5f689
Revises: d1f6b2c4e578
Create Date: 2026-10-13 18:00:00.000000

Дополнительные столы между обычными ("7/1 (Vip)" между 7 и 8).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2a7c3d5f689'
down_revision = 'd1f6b2c4e578'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'extra_tables',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('table_no', sa.Integer(), nullable=False),
        sa.Column('after_table', sa.Integer(), nullable=False),
        sa.Column('sub_index', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('club_id', 'table_no', name='uq_extra_tables_club_table'),
    )
    op.create_index('ix_extra_tables_club_id', 'extra_tables', ['club_id'], unique=False)


def downgrade():
    op.drop_index('ix_extra_tables_club_id', table_name='extra_tables')
    op.drop_table('extra_tables')
