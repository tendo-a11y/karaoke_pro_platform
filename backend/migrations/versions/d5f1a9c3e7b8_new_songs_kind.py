"""new_songs kind: new / duet lists

Revision ID: d5f1a9c3e7b8
Revises: c4e8a1d7f3b2
Create Date: 2026-11-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "d5f1a9c3e7b8"
down_revision = "c4e8a1d7f3b2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("new_songs", sa.Column("kind", sa.String(length=16), nullable=False, server_default="new"))


def downgrade():
    op.drop_column("new_songs", "kind")
