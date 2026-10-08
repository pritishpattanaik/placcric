"""Friendly-match category and the AI request log.

Adds tournaments.kind ('tournament' | 'friendly') and creates the "Friendly Match" category
(a container for one-off matches between any teams, so overs limits are the widest allowed).
Adds ai_requests: an audit log and cache of AI analyses (no API keys are stored).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('kind', sa.String(16), server_default='tournament', nullable=False))
    op.create_check_constraint('ck_tournaments_kind', 'tournaments', "kind IN ('tournament', 'friendly')")
    op.execute("""
        INSERT INTO tournaments (provider, external_id, name, slug, overs_per_innings, max_overs_per_bowler, kind)
        SELECT 'placcric', NULL, 'Friendly Match', '', 50, 50, 'friendly'
        WHERE NOT EXISTS (SELECT 1 FROM tournaments WHERE name = 'Friendly Match')
    """)
    op.create_table(
        'ai_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('subject', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('cache_key', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('answer', sa.Text(), server_default='', nullable=False),
        sa.Column('error', sa.Text(), server_default='', nullable=False),
        sa.CheckConstraint("status IN ('ok', 'error')", name='ck_ai_requests_status'),
        sa.PrimaryKeyConstraint('id', name='pk_ai_requests'),
    )
    op.create_index('ix_ai_requests_created', 'ai_requests', ['created_at'])
    op.create_index('ix_ai_requests_cache', 'ai_requests', ['cache_key'])


def downgrade():
    op.drop_table('ai_requests')
    # Friendly matches would lose their category; refuse rather than silently orphan them.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM matches m JOIN tournaments t ON t.id = m.tournament_id WHERE t.kind = 'friendly') THEN
            RAISE EXCEPTION 'Friendly matches exist; back up and remove them before downgrading below 0003';
          END IF;
        END $$;
    """)
    op.execute("DELETE FROM tournaments WHERE kind = 'friendly'")
    op.drop_constraint('ck_tournaments_kind', 'tournaments', type_='check')
    op.drop_column('tournaments', 'kind')
