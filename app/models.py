"""SQLAlchemy 2 models. The schema itself is created only by Alembic migrations in migrations/versions.

Cricket overs are stored as integer legal balls (`balls`). Match and player IDs are the
source provider's IDs (currently CricHeroes) and are never reassigned when names change.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, String, Text, text)
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


class Match(Base):
    __tablename__ = 'matches'
    __table_args__ = (CheckConstraint('team1 <> team2', name='distinct_teams'),
                      CheckConstraint('winner IN (team1, team2)', name='winner_is_participant'),
                      Index('ix_matches_date', 'date'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
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


CRICKET_TABLES = ('teams', 'players', 'roster_entries', 'matches', 'innings', 'batting', 'bowling', 'notes',
                  'import_log')
