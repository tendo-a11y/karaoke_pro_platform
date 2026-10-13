"""add services.temp_hidden (KJ: временно убрать категорию у гостей)

Revision ID: f9a3c7d1e2b5
Revises: e2a7c3d5f689
Create Date: 2026-10-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9a3c7d1e2b5'
down_revision = 'e2a7c3d5f689'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.add_column(sa.Column('temp_hidden', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('services', schema=None) as batch_op:
        batch_op.drop_column('temp_hidden')
