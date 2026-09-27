"""add table_close_requests

Revision ID: b7d4f291c5a3
Revises: a4f6d1c8b3e7
Create Date: 2026-09-27 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d4f291c5a3'
down_revision = 'a4f6d1c8b3e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('table_close_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('table_no', sa.Integer(), nullable=False),
    sa.Column('requested_by_guest_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('hide_receipt', sa.Boolean(), nullable=False),
    sa.Column('member_guest_ids', sa.JSON(), nullable=True),
    sa.Column('receipt_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id'], ),
    sa.ForeignKeyConstraint(['decided_by'], ['kj_operators.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('table_close_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_table_close_requests_club_id'), ['club_id'], unique=False)
        batch_op.create_index('ix_table_close_requests_lookup', ['club_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_table_close_requests_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('table_close_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_table_close_requests_status'))
        batch_op.drop_index('ix_table_close_requests_lookup')
        batch_op.drop_index(batch_op.f('ix_table_close_requests_club_id'))

    op.drop_table('table_close_requests')
