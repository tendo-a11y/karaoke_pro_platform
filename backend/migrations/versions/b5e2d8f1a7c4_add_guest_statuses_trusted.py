"""add guest_statuses.trusted for auto-accept

Revision ID: b5e2d8f1a7c4
Revises: a8c2e5f1d967
"""
import sqlalchemy as sa
from alembic import op

revision = 'b5e2d8f1a7c4'
down_revision = 'a8c2e5f1d967'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('guest_statuses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trusted', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    with op.batch_alter_table('guest_statuses', schema=None) as batch_op:
        batch_op.drop_column('trusted')
