"""Initial PostgreSQL schema: cricket data, notes, import history and interim PIN auth.

Mirrors the legacy SQLite schema (user_version 1) with explicit types and constraints.
Overs are stored as integer legal balls. Seed data is NOT inserted here; use
`python3 -m app.cli seed` explicitly.

Revision ID: 0001
Revises:
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_teams'),
        sa.UniqueConstraint('name', name='uq_teams_name'),
    )
    op.create_table(
        'players',
        sa.Column('id', sa.String(32), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(32), server_default='cricheroes', nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_players'),
    )
    op.create_table(
        'roster_entries',
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_roster_entries_team_id'),
        sa.PrimaryKeyConstraint('team_id', 'name', name='pk_roster_entries'),
    )
    op.create_table(
        'matches',
        sa.Column('id', sa.String(32), nullable=False),
        sa.Column('provider', sa.String(32), server_default='cricheroes', nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('venue', sa.Text(), nullable=False),
        sa.Column('team1', sa.Integer(), nullable=False),
        sa.Column('team2', sa.Integer(), nullable=False),
        sa.Column('winner', sa.Integer(), nullable=False),
        sa.Column('result', sa.Text(), nullable=False),
        sa.Column('toss', sa.Text(), server_default='', nullable=False),
        sa.Column('pom', sa.Text(), server_default='', nullable=False),
        sa.Column('dls', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('warning', sa.Text(), server_default='', nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('retrieved_at', sa.Text(), nullable=False),
        sa.CheckConstraint('team1 <> team2', name='ck_matches_distinct_teams'),
        sa.CheckConstraint('winner IN (team1, team2)', name='ck_matches_winner_is_participant'),
        sa.ForeignKeyConstraint(['team1'], ['teams.id'], name='fk_matches_team1'),
        sa.ForeignKeyConstraint(['team2'], ['teams.id'], name='fk_matches_team2'),
        sa.ForeignKeyConstraint(['winner'], ['teams.id'], name='fk_matches_winner'),
        sa.PrimaryKeyConstraint('id', name='pk_matches'),
    )
    op.create_index('ix_matches_date', 'matches', ['date'])
    op.create_table(
        'innings',
        sa.Column('match_id', sa.String(32), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('wickets', sa.Integer(), nullable=False),
        sa.Column('balls', sa.Integer(), nullable=False),
        sa.Column('extras', sa.Integer(), nullable=False),
        sa.CheckConstraint('number >= 1', name='ck_innings_number_positive'),
        sa.CheckConstraint('runs >= 0 AND balls >= 0 AND extras >= 0', name='ck_innings_non_negative'),
        sa.CheckConstraint('wickets BETWEEN 0 AND 10', name='ck_innings_wickets_range'),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE', name='fk_innings_match_id'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_innings_team_id'),
        sa.PrimaryKeyConstraint('match_id', 'number', name='pk_innings'),
    )
    op.create_index('ix_innings_team', 'innings', ['team_id', 'match_id'])
    op.create_table(
        'batting',
        sa.Column('match_id', sa.String(32), nullable=False),
        sa.Column('innings_number', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.String(32), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('balls', sa.Integer(), nullable=False),
        sa.Column('fours', sa.Integer(), nullable=False),
        sa.Column('sixes', sa.Integer(), nullable=False),
        sa.Column('dismissal', sa.Text(), server_default='', nullable=False),
        sa.Column('not_out', sa.Boolean(), nullable=False),
        sa.CheckConstraint('runs >= 0 AND balls >= 0 AND fours >= 0 AND sixes >= 0', name='ck_batting_non_negative'),
        sa.ForeignKeyConstraint(['match_id', 'innings_number'], ['innings.match_id', 'innings.number'],
                                ondelete='CASCADE', name='fk_batting_innings'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], name='fk_batting_player_id'),
        sa.PrimaryKeyConstraint('match_id', 'innings_number', 'player_id', name='pk_batting'),
    )
    op.create_index('ix_batting_player', 'batting', ['player_id', 'match_id'])
    op.create_table(
        'bowling',
        sa.Column('match_id', sa.String(32), nullable=False),
        sa.Column('innings_number', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.String(32), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('balls', sa.Integer(), nullable=False),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('wickets', sa.Integer(), nullable=False),
        sa.Column('dots', sa.Integer(), nullable=False),
        sa.Column('wides', sa.Integer(), nullable=False),
        sa.Column('no_balls', sa.Integer(), nullable=False),
        sa.CheckConstraint('balls >= 0 AND runs >= 0 AND dots >= 0 AND wides >= 0 AND no_balls >= 0',
                           name='ck_bowling_non_negative'),
        sa.CheckConstraint('wickets BETWEEN 0 AND 10', name='ck_bowling_wickets_range'),
        sa.CheckConstraint('dots <= balls', name='ck_bowling_dots_within_balls'),
        sa.ForeignKeyConstraint(['match_id', 'innings_number'], ['innings.match_id', 'innings.number'],
                                ondelete='CASCADE', name='fk_bowling_innings'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], name='fk_bowling_player_id'),
        sa.PrimaryKeyConstraint('match_id', 'innings_number', 'player_id', name='pk_bowling'),
    )
    op.create_index('ix_bowling_player', 'bowling', ['player_id', 'match_id'])
    op.create_table(
        'notes',
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_notes_team_id'),
        sa.PrimaryKeyConstraint('team_id', name='pk_notes'),
    )
    op.create_table(
        'import_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('matches', sa.Integer(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_import_log'),
    )
    # Interim PIN authentication; replaced by Google OpenID Connect in Milestone 2.
    op.create_table(
        'pin_credentials',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('salt', sa.Text(), nullable=False),
        sa.Column('pin_hash', sa.Text(), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_pin_credentials_single_row'),
        sa.PrimaryKeyConstraint('id', name='pk_pin_credentials'),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('csrf', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('token_hash', name='pk_auth_sessions'),
    )
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'])
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ip', sa.Text(), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_login_attempts'),
    )
    op.create_index('ix_login_attempts_ip_time', 'login_attempts', ['ip', 'attempted_at'])


def downgrade():
    for table in ('login_attempts', 'auth_sessions', 'pin_credentials', 'import_log', 'notes', 'bowling', 'batting',
                  'innings', 'matches', 'roster_entries', 'players', 'teams'):
        op.drop_table(table)
