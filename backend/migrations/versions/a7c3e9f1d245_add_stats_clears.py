"""add stats_clears

Revision ID: a7c3e9f1d245
Revises: f4b8d2e6a913
Create Date: 2026-10-09 18:00:00.000000

Очистка статистики в каждой панели за день/неделю/месяц/год.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e9f1d245'
down_revision = 'f4b8d2e6a913'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stats_clears',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('owner', sa.String(length=64), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stats_clears_scope_owner', 'stats_clears', ['scope', 'owner'], unique=False)


def downgrade():
    op.drop_index('ix_stats_clears_scope_owner', table_name='stats_clears')
    op.drop_table('stats_clears')
