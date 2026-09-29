"""add services.kj_only (Bonus category restricted to KJ only)

Revision ID: a47725a2b8ae
Revises: b7d4f291c5a3
Create Date: 2026-09-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a47725a2b8ae'
down_revision = 'b7d4f291c5a3'
branch_labels = None
depends_on = None


def upgrade():
    # Столбец добавляем со значением по умолчанию False для всех уже
    # существующих категорий (иначе Postgres не примет NOT NULL на непустой
    # таблице) — server_default снимаем сразу после заполнения, дальше
    # значение всегда выставляется явно кодом (services/category_service.py).
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kj_only', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.alter_column('kj_only', server_default=None)

    # У уже существующих клубов категория "BONUS" была заведена раньше (см.
    # DEFAULT_CATEGORIES в services/category_service.py) ещё без этого
    # признака — помечаем её задним числом, чтобы решение пользователя
    # ("Bonus может применить только роль 2, гости её не видят и не могут ей
    # заказать") подействовало и на уже существующие клубы, а не только на
    # новые, у которых список категорий заведётся заново с этим флагом.
    op.execute("UPDATE services SET kj_only = true WHERE name = 'BONUS'")


def downgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('kj_only')
