"""add services.section (Основные / Дополнительные отсеки категорий)

Revision ID: c9d4e7a2f301
Revises: b5e2d8f1a7c4
Create Date: 2026-10-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d4e7a2f301'
down_revision = 'b5e2d8f1a7c4'
branch_labels = None
depends_on = None


def upgrade():
    # Все существующие категории сначала попадают в "main" (server_default),
    # затем всё, кроме KARAOKE и INTERNET, переводится в "extra" (как сейчас
    # выглядит список у гостя). Дальше отсек меняется только явно (KJ), и
    # переименование категории на него не влияет.
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('section', sa.String(length=16), nullable=False, server_default='main'))
    op.execute(
        "UPDATE services SET section = 'extra' "
        "WHERE upper(trim(name)) NOT IN ('KARAOKE', 'INTERNET')"
    )


def downgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('section')
