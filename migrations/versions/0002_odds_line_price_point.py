"""Add line and price_point columns to odds.

Additive, backward-compatible: both nullable, existing rows get NULL for
both (the original single-snapshot convention), no data migration needed.
Enables Asian Handicap (needs a numeric line) and opening/closing odds
(needs a phase distinction) without overloading recorded_at, which
represents an actual timestamp the ingest pipeline doesn't have for this
data.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("odds", sa.Column("line", sa.Float, nullable=True))
    op.add_column("odds", sa.Column("price_point", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("odds", "price_point")
    op.drop_column("odds", "line")
