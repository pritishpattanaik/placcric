"""SQLAlchemy 2 models. The schema itself is created only by Alembic migrations in migrations/versions.

Cricket overs are stored as integer legal balls (`balls`). Match and player IDs are the
source provider's IDs (currently CricHeroes) and are never reassigned when names change.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {'ix': 'ix_%(table_name)s_%(column_0_N_name)s', 'uq': 'uq_%(table_name)s_%(column_0_N_name)s',
          'ck': 'ck_%(table_name)s_%(constraint_name)s', 'fk': 'fk_%(table_name)s_%(column_0_N_name)s',
          'pk': 'pk_%(table_name)s'}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING


class Team(Base):
    __tablename__ = 'teams'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class RosterEntry(Base):
    """A public club listing. Not a confirmed tournament squad and never merged with players by name."""
    __tablename__ = 'roster_entries'
    team_id: Mapped[int] = mapped_column(ForeignKey('teams.id'), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)


class Player(Base):
    __tablename__ = 'players'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), server_default='cricheroes')


class Tournament(Base):
    """A competition with its own playing conditions. external_id is the provider's tournament ID."""
    __tablename__ = 'tournaments'
    __table_args__ = (UniqueConstraint('provider', 'external_id', name='uq_tournaments_provider_external_id'),
                      CheckConstraint('overs_per_innings BETWEEN 1 AND 50', name='overs_range'),
                      CheckConstraint('max_overs_per_bowler BETWEEN 1 AND overs_per_innings', name='bowler_overs_range'),
                      CheckConstraint("kind IN ('tournament', 'friendly')", name='kind'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), server_default='cricheroes')
    # 'friendly' collects one-off matches between any teams; overs vary per match.
    kind: Mapped[str] = mapped_column(String(16), server_default='tournament')
    external_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    slug: Mapped[str] = mapped_column(Text, server_default='')
    overs_per_innings: Mapped[int] = mapped_column(Integer)
    max_overs_per_bowler: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))


class Match(Base):
    __tablename__ = 'matches'
    __table_args__ = (CheckConstraint('team1 <> team2', name='distinct_teams'),
                      CheckConstraint('winner IN (team1, team2)', name='winner_is_participant'),
                      Index('ix_matches_date', 'date'), Index('ix_matches_tournament', 'tournament_id', 'date'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey('tournaments.id'))
    # Competition stage as given by the source, e.g. "Semi Final"; empty for league matches.
    stage: Mapped[str] = mapped_column(Text, server_default='')
    provider: Mapped[str] = mapped_column(String(32), server_default='cricheroes')
    date: Mapped[date] = mapped_column(Date)
    venue: Mapped[str] = mapped_column(Text)
    team1: Mapped[int] = mapped_column(ForeignKey('teams.id'))
    team2: Mapped[int] = mapped_column(ForeignKey('teams.id'))
    winner: Mapped[int] = mapped_column(ForeignKey('teams.id'))
    result: Mapped[str] = mapped_column(Text)
    toss: Mapped[str] = mapped_column(Text, server_default='')
    pom: Mapped[str] = mapped_column(Text, server_default='')
    dls: Mapped[bool] = mapped_column(Boolean, server_default=text('false'))
    warning: Mapped[str] = mapped_column(Text, server_default='')
    source_url: Mapped[str] = mapped_column(Text)
    # Kept exactly as supplied by the source (may be a date or a timestamp).
    retrieved_at: Mapped[str] = mapped_column(Text)


class Innings(Base):
    __tablename__ = 'innings'
    __table_args__ = (CheckConstraint('number >= 1', name='number_positive'),
                      CheckConstraint('runs >= 0 AND balls >= 0 AND extras >= 0', name='non_negative'),
                      CheckConstraint('wickets BETWEEN 0 AND 10', name='wickets_range'),
                      Index('ix_innings_team', 'team_id', 'match_id'))
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey('teams.id'))
    runs: Mapped[int] = mapped_column(Integer)
    wickets: Mapped[int] = mapped_column(Integer)
    balls: Mapped[int] = mapped_column(Integer)
    extras: Mapped[int] = mapped_column(Integer)


class Batting(Base):
    __tablename__ = 'batting'
    __table_args__ = (ForeignKeyConstraint(['match_id', 'innings_number'], ['innings.match_id', 'innings.number'],
                                           ondelete='CASCADE', name='fk_batting_innings'),
                      CheckConstraint('runs >= 0 AND balls >= 0 AND fours >= 0 AND sixes >= 0', name='non_negative'),
                      Index('ix_batting_player', 'player_id', 'match_id'))
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    innings_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    runs: Mapped[int] = mapped_column(Integer)
    balls: Mapped[int] = mapped_column(Integer)
    fours: Mapped[int] = mapped_column(Integer)
    sixes: Mapped[int] = mapped_column(Integer)
    dismissal: Mapped[str] = mapped_column(Text, server_default='')
    not_out: Mapped[bool] = mapped_column(Boolean)


class Bowling(Base):
    __tablename__ = 'bowling'
    __table_args__ = (ForeignKeyConstraint(['match_id', 'innings_number'], ['innings.match_id', 'innings.number'],
                                           ondelete='CASCADE', name='fk_bowling_innings'),
                      CheckConstraint('balls >= 0 AND runs >= 0 AND dots >= 0 AND wides >= 0 AND no_balls >= 0',
                                      name='non_negative'),
                      CheckConstraint('wickets BETWEEN 0 AND 10', name='wickets_range'),
                      CheckConstraint('dots <= balls', name='dots_within_balls'),
                      Index('ix_bowling_player', 'player_id', 'match_id'))
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    innings_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    balls: Mapped[int] = mapped_column(Integer)
    runs: Mapped[int] = mapped_column(Integer)
    wickets: Mapped[int] = mapped_column(Integer)
    dots: Mapped[int] = mapped_column(Integer)
    wides: Mapped[int] = mapped_column(Integer)
    no_balls: Mapped[int] = mapped_column(Integer)


class Note(Base):
    __tablename__ = 'notes'
    team_id: Mapped[int] = mapped_column(ForeignKey('teams.id'), primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportLog(Base):
    __tablename__ = 'import_log'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    matches: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    # SHA-256 of the canonical JSON bundle; NULL for history migrated from SQLite.
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ImportBatch(Base):
    """An uploaded file, parsed and validated but not published until approved."""
    __tablename__ = 'import_batches'
    __table_args__ = (CheckConstraint("source_kind IN ('json', 'pdf')", name='source_kind'),
                      CheckConstraint("status IN ('staged', 'approved', 'rejected')", name='status'),
                      Index('ix_import_batches_created', 'created_at'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(16))
    # Display only; the raw file is stored privately under a generated name.
    original_filename: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    raw_path: Mapped[str] = mapped_column(Text)
    tournament_id: Mapped[int] = mapped_column(ForeignKey('tournaments.id'))
    status: Mapped[str] = mapped_column(String(16))
    # Parsed records, source metadata, errors and warnings.
    payload: Mapped[dict] = mapped_column(JSONB)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class MatchRevision(Base):
    """Every published version of a match. The scorecard tables hold the latest revision."""
    __tablename__ = 'match_revisions'
    __table_args__ = (UniqueConstraint('match_id', 'number', name='uq_match_revisions_match_id_number'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id'))
    number: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey('import_batches.id'), nullable=True)
    note: Mapped[str] = mapped_column(Text, server_default='')


class PlayerAlias(Base):
    """A scorecard name confirmed by an admin as a given player, scoped to the team the name appeared for."""
    __tablename__ = 'player_aliases'
    __table_args__ = (UniqueConstraint('team_id', 'alias_key', name='uq_player_aliases_team_id_alias_key'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey('teams.id'))
    alias_key: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'))
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey('import_batches.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiRequest(Base):
    """Audit log and cache of AI analyses: what was asked, which model, token usage, and the answer.
    The evidence sent is identified by its hash; the API key is never stored."""
    __tablename__ = 'ai_requests'
    __table_args__ = (CheckConstraint("status IN ('ok', 'error')", name='status'),
                      Index('ix_ai_requests_created', 'created_at'), Index('ix_ai_requests_cache', 'cache_key'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    answer: Mapped[str] = mapped_column(Text, server_default='')
    error: Mapped[str] = mapped_column(Text, server_default='')


# --- Interim single-user PIN authentication -------------------------------------------------
# Retained only until Milestone 2 replaces it with Google OpenID Connect. These tables are never
# populated by the SQLite migration (PIN hashes, sessions and login attempts are not migrated).

class PinCredential(Base):
    __tablename__ = 'pin_credentials'
    __table_args__ = (CheckConstraint('id = 1', name='single_row'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    salt: Mapped[str] = mapped_column(Text)
    pin_hash: Mapped[str] = mapped_column(Text)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    __table_args__ = (Index('ix_login_attempts_ip_time', 'ip', 'attempted_at'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


CRICKET_TABLES = ('tournaments', 'teams', 'players', 'roster_entries', 'matches', 'innings', 'batting', 'bowling',
                  'notes', 'import_log', 'import_batches', 'match_revisions', 'player_aliases', 'ai_requests')
