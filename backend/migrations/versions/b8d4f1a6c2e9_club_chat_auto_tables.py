"""club chat_auto_tables

Revision ID: b8d4f1a6c2e9
Revises: a7c3e9f2d5b1
"""

from alembic import op
import sqlalchemy as sa


revision = "b8d4f1a6c2e9"
down_revision = "a7c3e9f2d5b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clubs") as batch:
        batch.add_column(
            sa.Column("chat_auto_tables", sa.Integer(), nullable=False, server_default="5")
        )


def downgrade():
    with op.batch_alter_table("clubs") as batch:
        batch.drop_column("chat_auto_tables")
