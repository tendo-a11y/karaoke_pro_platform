"""add club cashback

Revision ID: b8d4f0a2c356
Revises: a7c3e9f1d245
Create Date: 2026-10-09 22:00:00.000000

Кешбек от клуба супер-админу: процент клуба + начисления за каждый вечер.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d4f0a2c356'
down_revision = 'a7c3e9f1d245'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clubs', sa.Column('cashback_percent', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('clubs', sa.Column('cashback_vip_only', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Уже существующим клубам — 5% (как прежняя общая комиссия); супер-админ поменяет вручную.
    op.execute("UPDATE clubs SET cashback_percent = 5")
    op.create_table(
        'club_cashbacks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revenue_total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('revenue_vip', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('revenue_regular', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('guests_vip', sa.Integer(), nullable=False),
        sa.Column('guests_regular', sa.Integer(), nullable=False),
        sa.Column('percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('vip_only', sa.Boolean(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_club_cashbacks_club_id', 'club_cashbacks', ['club_id'], unique=False)


def downgrade():
    op.drop_index('ix_club_cashbacks_club_id', table_name='club_cashbacks')
    op.drop_table('club_cashbacks')
    op.drop_column('clubs', 'cashback_vip_only')
    op.drop_column('clubs', 'cashback_percent')
