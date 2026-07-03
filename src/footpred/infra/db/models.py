"""SQLAlchemy 2.0 ORM models. Mirrors domain entities 1:1.

Nothing above the infra layer imports this module.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeagueRow(Base):
    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TeamRow(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128))
    normalized_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)


class TeamAliasRow(Base):
    __tablename__ = "team_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    alias: Mapped[str] = mapped_column(String(128))
    normalized_alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class MatchRow(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    match_date: Mapped[date] = mapped_column(Date, index=True)
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ht_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ht_away: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ft_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ft_away: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)

    __table_args__ = (
        Index("ix_matches_pairing_date",
              "league_id", "home_team_id", "away_team_id", "match_date"),
    )


class MatchSourceRow(Base):
    __tablename__ = "match_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_ext"),)


class OddsRow(Base):
    __tablename__ = "odds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    selection: Mapped[str] = mapped_column(String(32))
    decimal_odds: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportRow(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(256))
    profile_name: Mapped[str] = mapped_column(String(64))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_enriched: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
