"""Tournaments, staged import batches, match revisions and confirmed player aliases.

Existing matches all belong to the bundled tournament (CricHeroes 2194193); when any exist,
that tournament is created and assigned to them before tournament_id becomes NOT NULL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tournaments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(32), server_default='cricheroes', nullable=False),
        sa.Column('external_id', sa.String(32), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('slug', sa.Text(), server_default='', nullable=False),
        sa.Column('overs_per_innings', sa.Integer(), nullable=False),
        sa.Column('max_overs_per_bowler', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('overs_per_innings BETWEEN 1 AND 50', name='ck_tournaments_overs_range'),
        sa.CheckConstraint('max_overs_per_bowler BETWEEN 1 AND overs_per_innings',
                           name='ck_tournaments_bowler_overs_range'),
        sa.PrimaryKeyConstraint('id', name='pk_tournaments'),
        sa.UniqueConstraint('name', name='uq_tournaments_name'),
        sa.UniqueConstraint('provider', 'external_id', name='uq_tournaments_provider_external_id'),
    )
    op.add_column('matches', sa.Column('tournament_id', sa.Integer(), nullable=True))
    op.add_column('matches', sa.Column('stage', sa.Text(), server_default='', nullable=False))
    op.execute("""
        INSERT INTO tournaments (provider, external_id, name, slug, overs_per_innings, max_overs_per_bowler)
        SELECT 'cricheroes', '2194193', 'Diwhyn Choice T25 Cricket Carnival — Season 2',
               'diwhyn-choice-t25-cricket-carnival-season-2', 25, 5
        WHERE EXISTS (SELECT 1 FROM matches)
    """)
    op.execute("UPDATE matches SET tournament_id = (SELECT id FROM tournaments WHERE external_id = '2194193')")
    op.alter_column('matches', 'tournament_id', nullable=False)
    op.create_foreign_key('fk_matches_tournament_id', 'matches', 'tournaments', ['tournament_id'], ['id'])
    op.create_index('ix_matches_tournament', 'matches', ['tournament_id', 'date'])

    op.create_table(
        'import_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.Column('source_kind', sa.String(16), nullable=False),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=False),
        sa.Column('raw_path', sa.Text(), nullable=False),
        sa.Column('tournament_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.Text(), nullable=True),
        sa.CheckConstraint("source_kind IN ('json', 'pdf')", name='ck_import_batches_source_kind'),
        sa.CheckConstraint("status IN ('staged', 'approved', 'rejected')", name='ck_import_batches_status'),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], name='fk_import_batches_tournament_id'),
        sa.PrimaryKeyConstraint('id', name='pk_import_batches'),
    )
    op.create_index('ix_import_batches_created', 'import_batches', ['created_at'])
    op.create_table(
        'match_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.String(32), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('content', JSONB(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name='fk_match_revisions_match_id'),
        sa.ForeignKeyConstraint(['batch_id'], ['import_batches.id'], name='fk_match_revisions_batch_id'),
        sa.PrimaryKeyConstraint('id', name='pk_match_revisions'),
        sa.UniqueConstraint('match_id', 'number', name='uq_match_revisions_match_id_number'),
    )
    op.create_table(
        'player_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('alias_key', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('player_id', sa.String(32), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name='fk_player_aliases_team_id'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], name='fk_player_aliases_player_id'),
        sa.ForeignKeyConstraint(['batch_id'], ['import_batches.id'], name='fk_player_aliases_batch_id'),
        sa.PrimaryKeyConstraint('id', name='pk_player_aliases'),
        sa.UniqueConstraint('team_id', 'alias_key', name='uq_player_aliases_team_id_alias_key'),
    )


def downgrade():
    op.drop_table('player_aliases')
    op.drop_table('match_revisions')
    op.drop_table('import_batches')
    op.drop_index('ix_matches_tournament', table_name='matches')
    op.drop_constraint('fk_matches_tournament_id', 'matches', type_='foreignkey')
    op.drop_column('matches', 'stage')
    op.drop_column('matches', 'tournament_id')
    op.drop_table('tournaments')
