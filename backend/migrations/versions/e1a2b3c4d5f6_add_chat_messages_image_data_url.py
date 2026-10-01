"""add chat_messages image_data_url

Revision ID: e1a2b3c4d5f6
Revises: c4e9f27a1b56
Create Date: 2026-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e1a2b3c4d5f6'
down_revision = 'c4e9f27a1b56'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_data_url', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_column('image_data_url')
