"""add club payment mode (percent / subscription)

Revision ID: c9e5a1b3d467
Revises: b8d4f0a2c356
Create Date: 2026-10-10 12:00:00.000000

Способ оплаты системы клубом: кешбек % или абонплата в евро в месяц.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9e5a1b3d467'
down_revision = 'b8d4f0a2c356'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clubs', sa.Column('payment_mode', sa.String(length=16), nullable=False, server_default='percent'))
    op.add_column('clubs', sa.Column('payment_mode_next', sa.String(length=16), nullable=True))
    op.add_column('clubs', sa.Column('payment_mode_next_from', sa.String(length=7), nullable=True))
    op.add_column('clubs', sa.Column('subscription_eur', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('club_cashbacks', sa.Column('kind', sa.String(length=16), nullable=False, server_default='evening'))
    op.add_column('club_cashbacks', sa.Column('mode', sa.String(length=16), nullable=False, server_default='percent'))
    op.add_column('club_cashbacks', sa.Column('currency', sa.String(length=3), nullable=False, server_default='MDL'))
    op.add_column('club_cashbacks', sa.Column('period', sa.String(length=7), nullable=True))
    op.create_unique_constraint('uq_club_cashbacks_period', 'club_cashbacks', ['club_id', 'kind', 'period'])


def downgrade():
    op.drop_constraint('uq_club_cashbacks_period', 'club_cashbacks', type_='unique')
    op.drop_column('club_cashbacks', 'period')
    op.drop_column('club_cashbacks', 'currency')
    op.drop_column('club_cashbacks', 'mode')
    op.drop_column('club_cashbacks', 'kind')
    op.drop_column('clubs', 'subscription_eur')
    op.drop_column('clubs', 'payment_mode_next_from')
    op.drop_column('clubs', 'payment_mode_next')
    op.drop_column('clubs', 'payment_mode')
