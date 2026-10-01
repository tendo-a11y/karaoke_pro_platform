"""add chat_messages service_id

Revision ID: f2b4c6d8e0a1
Revises: e1a2b3c4d5f6
Create Date: 2026-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f2b4c6d8e0a1'
down_revision = 'e1a2b3c4d5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_chat_messages_service_id_services', 'services', ['service_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_constraint('fk_chat_messages_service_id_services', type_='foreignkey')
        batch_op.drop_column('service_id')
