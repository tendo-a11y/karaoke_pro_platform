"""add services.link_default (категория для заказов по ссылке)

Revision ID: d2f8a6b1c904
Revises: c9d4e7a2f301
Create Date: 2026-10-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f8a6b1c904'
down_revision = 'c9d4e7a2f301'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('link_default', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.alter_column('link_default', server_default=None)
    # Для уже существующих клубов сохраняем прежнее поведение: категория INTERNET
    # подставляется при заказе по ссылке. Если её переименовали, KJ отметит сам в панели.
    op.execute("UPDATE services SET link_default = true WHERE upper(trim(name)) = 'INTERNET'")


def downgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('link_default')
