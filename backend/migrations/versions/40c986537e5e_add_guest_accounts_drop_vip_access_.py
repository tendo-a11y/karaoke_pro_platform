"""add guest_accounts, drop vip access_code (ТЗ п.45)

Revision ID: 40c986537e5e
Revises: f848a23791b7
Create Date: 2026-09-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '40c986537e5e'
down_revision = '051b5b391777'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('guest_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('google_sub', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('club_id', 'telegram_user_id', name='uq_guest_accounts_club_user'),
    sa.UniqueConstraint('club_id', 'google_sub', name='uq_guest_accounts_club_google_sub'),
    )
    with op.batch_alter_table('guest_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_guest_accounts_club_id'), ['club_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_guest_accounts_google_sub'), ['google_sub'], unique=False)
        batch_op.create_index(batch_op.f('ix_guest_accounts_telegram_user_id'), ['telegram_user_id'], unique=False)

    with op.batch_alter_table('vip_clients', schema=None) as batch_op:
        batch_op.drop_index('ix_vip_clients_access_code')
        batch_op.drop_column('access_code')


def downgrade():
    with op.batch_alter_table('vip_clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('access_code', sa.VARCHAR(length=16), nullable=True))
        batch_op.create_index('ix_vip_clients_access_code', ['access_code'], unique=True)

    with op.batch_alter_table('guest_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_guest_accounts_telegram_user_id'))
        batch_op.drop_index(batch_op.f('ix_guest_accounts_google_sub'))
        batch_op.drop_index(batch_op.f('ix_guest_accounts_club_id'))

    op.drop_table('guest_accounts')
