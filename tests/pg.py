"""Isolated PostgreSQL test database support.

Integration tests use TEST_DATABASE_URL (never DATABASE_URL). The database name must end in
`_test` because its `public` schema is dropped and recreated. If TEST_DATABASE_URL is unset the
PostgreSQL tests are skipped with a visible reason; set PLACCRIC_REQUIRE_PG=1 to fail instead.
SQLite is never used as a substitute.
"""
import os
import unittest

from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import load_env_file, normalise_database_url
from app.db import alembic_config, make_engine
from app.models import Base

SKIP_REASON = 'TEST_DATABASE_URL is not set; PostgreSQL integration tests skipped (see README "Tests").'


def test_database_url():
    load_env_file()
    raw = os.environ.get('TEST_DATABASE_URL')
    if not raw:
        if os.environ.get('PLACCRIC_REQUIRE_PG') == '1':
            raise RuntimeError(SKIP_REASON)
        raise unittest.SkipTest(SKIP_REASON)
    url = normalise_database_url(raw, 'TEST_DATABASE_URL')
    name = make_url(url).database or ''
    if not name.endswith('_test'):
        raise RuntimeError(f'Refusing to use database "{name}" for tests: its name must end in _test.')
    app_url = os.environ.get('DATABASE_URL')
    if app_url and make_url(normalise_database_url(app_url)).database == name:
        raise RuntimeError('TEST_DATABASE_URL must point at a different database from DATABASE_URL.')
    return url


def reset_schema(engine):
    with engine.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))


def upgrade(url, revision='head'):
    command.upgrade(alembic_config(url), revision)


def truncate_all(engine):
    tables = ', '.join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f'TRUNCATE {tables} RESTART IDENTITY CASCADE'))


class PostgresTestCase(unittest.TestCase):
    """Fresh migrated schema per class; every table truncated before each test."""

    @classmethod
    def setUpClass(cls):
        cls.url = test_database_url()
        cls.engine = make_engine(cls.url)
        reset_schema(cls.engine)
        upgrade(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        truncate_all(self.engine)

    def seed(self):
        from app.ingestion.scorecards import seed
        with self.engine.begin() as db:
            return seed(db)
