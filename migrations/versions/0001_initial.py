"""Initial Sprint 1 schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("canonical_key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("country", sa.String(64), nullable=True),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("canonical_name", sa.String(128), nullable=False),
        sa.Column("normalized_key", sa.String(128), nullable=False, unique=True, index=True),
    )
    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("normalized_alias", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("profile_name", sa.String(64), nullable=False),
        sa.Column("rows_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_imported", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_duplicate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_enriched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("report_json", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("league_id", sa.Integer, sa.ForeignKey("leagues.id"), nullable=False, index=True),
        sa.Column("home_team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("away_team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("match_date", sa.Date, nullable=False, index=True),
        sa.Column("kickoff_utc", sa.DateTime, nullable=True),
        sa.Column("ht_home", sa.Integer, nullable=True),
        sa.Column("ht_away", sa.Integer, nullable=True),
        sa.Column("ft_home", sa.Integer, nullable=True),
        sa.Column("ft_away", sa.Integer, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("import_id", sa.Integer, sa.ForeignKey("imports.id"), nullable=True),
        sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True, index=True),
    )
    op.create_index(
        "ix_matches_pairing_date", "matches",
        ["league_id", "home_team_id", "away_team_id", "match_date"],
    )
    op.create_table(
        "match_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("match_id", sa.Integer, sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_source_ext"),
    )
    op.create_table(
        "odds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("match_id", sa.Integer, sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("bookmaker", sa.String(32), nullable=False, index=True),
        sa.Column("market", sa.String(32), nullable=False, index=True),
        sa.Column("selection", sa.String(32), nullable=False),
        sa.Column("decimal_odds", sa.Float, nullable=False),
        sa.Column("recorded_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    for t in ("odds", "match_sources", "matches", "imports",
              "team_aliases", "teams", "leagues"):
        op.drop_table(t)
