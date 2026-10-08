"""Fall of wickets per innings (from scorecard PDFs), used for pivot-point analysis.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fall_of_wickets',
        sa.Column('match_id', sa.String(32), nullable=False),
        sa.Column('innings_number', sa.Integer(), nullable=False),
        sa.Column('wicket', sa.Integer(), nullable=False),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('balls', sa.Integer(), nullable=False),
        sa.Column('batter', sa.Text(), nullable=False),
        sa.CheckConstraint('wicket BETWEEN 1 AND 10', name='ck_fall_of_wickets_wicket_range'),
        sa.CheckConstraint('runs >= 0 AND balls >= 0', name='ck_fall_of_wickets_non_negative'),
        sa.ForeignKeyConstraint(['match_id', 'innings_number'], ['innings.match_id', 'innings.number'],
                                ondelete='CASCADE', name='fk_fall_of_wickets_innings'),
        sa.PrimaryKeyConstraint('match_id', 'innings_number', 'wicket', name='pk_fall_of_wickets'),
    )


def downgrade():
    op.drop_table('fall_of_wickets')
