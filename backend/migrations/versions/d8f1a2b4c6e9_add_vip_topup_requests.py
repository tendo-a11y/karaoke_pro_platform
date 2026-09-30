"""add vip_topup_requests

Revision ID: d8f1a2b4c6e9
Revises: 92cb15093592
Create Date: 2026-09-30 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8f1a2b4c6e9'
down_revision = '92cb15093592'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vip_topup_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id'], ),
    sa.ForeignKeyConstraint(['decided_by'], ['kj_operators.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('vip_topup_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vip_topup_requests_club_id'), ['club_id'], unique=False)
        batch_op.create_index('ix_vip_topup_requests_lookup', ['club_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_vip_topup_requests_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('vip_topup_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vip_topup_requests_status'))
        batch_op.drop_index('ix_vip_topup_requests_lookup')
        batch_op.drop_index(batch_op.f('ix_vip_topup_requests_club_id'))

    op.drop_table('vip_topup_requests')
