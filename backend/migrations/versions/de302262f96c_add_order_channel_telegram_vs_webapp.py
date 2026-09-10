"""add order channel (telegram vs webapp)

Revision ID: de302262f96c
Revises: 40c986537e5e
Create Date: 2026-09-08 22:53:58.780897

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de302262f96c'
down_revision = '40c986537e5e'
branch_labels = None
depends_on = None


def upgrade():
    # Ручная правка автогенерированного файла: у таблицы orders уже есть
    # строки, поэтому новую колонку с nullable=False нужно добавлять со
    # server_default, иначе Postgres откажется (не может понять, что писать
    # в channel для уже существующих заказов). Значение по умолчанию —
    # 'telegram': до появления Guest App это был единственный путь, поэтому
    # для всех старых записей это самое честное предположение, а на решение
    # о том, слать ли уведомление, оно повлиять уже не может — старые заказы
    # к этому моменту уже либо подтверждены/отклонены, либо доиграны.
    # Server_default снимаем сразу после заполнения — дальше значение всегда
    # проставляется явно самим кодом (routes/client.py, routes/guest.py,
    # services/vip_service.py::reorder_favorite).
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=20), nullable=False, server_default='telegram'))
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.alter_column('channel', server_default=None)


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('channel')
