"""add kj_suggestions

Revision ID: e2a7c4f9b153
Revises: d9f4b2c6e831
Create Date: 2026-10-09 12:00:00.000000

Предложения KJ по улучшению приложения для администрации.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2a7c4f9b153'
down_revision = 'd9f4b2c6e831'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kj_suggestions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('kj_name', sa.String(length=255), nullable=True),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.club_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('kj_suggestions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_kj_suggestions_club_id'), ['club_id'], unique=False)


def downgrade():
    with op.batch_alter_table('kj_suggestions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_kj_suggestions_club_id'))
    op.drop_table('kj_suggestions')
