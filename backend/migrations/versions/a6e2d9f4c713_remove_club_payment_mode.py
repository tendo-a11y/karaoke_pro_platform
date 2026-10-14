"""remove abandoned club payment mode (subscription) columns

Revision ID: a6e2d9f4c713
Revises: f9a3c7d1e2b5
Create Date: 2026-10-14 12:00:00.000000

Убираем заготовки отменённой абонплаты, добавленные в c9e5a1b3d467:
clubs.payment_mode, clubs.payment_mode_next, clubs.payment_mode_next_from,
clubs.subscription_eur. Нигде в коде, кроме моделей Club, не используются.
Таблица club_cashbacks и её колонки здесь не трогаем.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a6e2d9f4c713'
down_revision = 'f9a3c7d1e2b5'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('clubs', 'subscription_eur')
    op.drop_column('clubs', 'payment_mode_next_from')
    op.drop_column('clubs', 'payment_mode_next')
    op.drop_column('clubs', 'payment_mode')


def downgrade():
    op.add_column('clubs', sa.Column('payment_mode', sa.String(length=16), nullable=False, server_default='percent'))
    op.add_column('clubs', sa.Column('payment_mode_next', sa.String(length=16), nullable=True))
    op.add_column('clubs', sa.Column('payment_mode_next_from', sa.String(length=7), nullable=True))
    op.add_column('clubs', sa.Column('subscription_eur', sa.Numeric(precision=10, scale=2), nullable=True))
