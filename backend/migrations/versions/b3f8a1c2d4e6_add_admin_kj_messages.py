"""add admin_kj_messages (chat between club administration and KJ)

Revision ID: b3f8a1c2d4e6
Revises: f2b4c6d8e0a1
Create Date: 2026-10-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3f8a1c2d4e6'
down_revision = 'f2b4c6d8e0a1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('admin_kj_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('from_admin', sa.Boolean(), nullable=False),
    sa.Column('message_text', sa.Text(), nullable=False),
    sa.Column('is_read_by_kj', sa.Boolean(), nullable=False),
    sa.Column('is_read_by_admin', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('admin_kj_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_admin_kj_messages_club_id'), ['club_id'], unique=False)
        batch_op.create_index('ix_admin_kj_messages_club_created', ['club_id', 'created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('admin_kj_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_admin_kj_messages_club_created')
        batch_op.drop_index(batch_op.f('ix_admin_kj_messages_club_id'))
    op.drop_table('admin_kj_messages')
