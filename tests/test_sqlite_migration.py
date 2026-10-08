"""One-time SQLite → PostgreSQL migration tests."""
import tempfile
from pathlib import Path

from sqlalchemy import text

from app.analytics import profile, summary
from app.sqlite_migration import MigrationError, compare, file_sha256, migrate
from tests import legacy_sqlite
from tests.pg import PostgresTestCase

CRICKET = ('teams', 'players', 'roster_entries', 'matches', 'innings', 'batting', 'bowling', 'notes', 'import_log')


class SqliteMigrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.sqlite = Path(self.tmp.name) / 'placcric.sqlite3'
        self.team_ids = legacy_sqlite.build(self.sqlite, team_id_offset=100)

    def tearDown(self):
        self.tmp.cleanup()

    def counts(self):
        with self.engine.connect() as db:
            return {t: db.execute(text(f'SELECT count(*) FROM {t}')).scalar_one() for t in CRICKET}

    def test_dry_run_verifies_then_writes_nothing(self):
        before = file_sha256(self.sqlite)
        report = migrate(self.sqlite, self.engine, self.url, dry_run=True)
        self.assertTrue(report['dry_run'])
        self.assertFalse(report['committed'])
        self.assertEqual(report['tables']['matches']['rows'], 5)
        self.assertEqual(report['tables']['innings']['totals']['runs'], 1923)
        self.assertEqual(set(self.counts().values()), {0})
        self.assertEqual(file_sha256(self.sqlite), before)

    def test_migration_preserves_ids_data_and_excludes_auth(self):
        before = file_sha256(self.sqlite)
        report = migrate(self.sqlite, self.engine, self.url)
        self.assertTrue(report['committed'])
        self.assertEqual(report['not_migrated'], {'auth': 1, 'sessions': 1, 'login_attempts': 1, 'meta': 1})
        self.assertEqual(file_sha256(self.sqlite), before, 'SQLite source must not change')
        counts = self.counts()
        self.assertEqual({k: counts[k] for k in ('teams', 'matches', 'innings', 'notes', 'import_log', 'roster_entries')},
                         {'teams': 15, 'matches': 5, 'innings': 10, 'notes': 1, 'import_log': 1, 'roster_entries': 915})
        with self.engine.connect() as db:
            for table in ('pin_credentials', 'auth_sessions', 'login_attempts'):
                self.assertEqual(db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one(), 0, table)
            ucc = self.team_ids['UTKAL Cricket Club (UCC).']
            self.assertGreater(ucc, 100)
            self.assertEqual(db.execute(text('SELECT name FROM teams WHERE id=:i'), {'i': ucc}).scalar_one(),
                             'UTKAL Cricket Club (UCC).')
            note = db.execute(text('SELECT body, updated_at FROM notes WHERE team_id=:i'), {'i': ucc}).one()
            self.assertEqual(note.body, 'Open with spin; accents é, emoji 🏏 preserved')
            self.assertEqual(note.updated_at.isoformat(), '2026-10-07T10:30:00+00:00')
            self.assertEqual(db.execute(text('SELECT id FROM import_log')).scalar_one(), 4)
            s = summary(db)
            self.assertEqual((s['completed'], s['recorded_runs']), (5, 1923))
            self.assertEqual(summary(db, ucc)['recorded_runs'], 188)
            self.assertEqual(profile(db, '27014853')['wickets'], 7)
            self.assertIs(db.execute(text("SELECT dls FROM matches WHERE id='27291206'")).scalar_one(), True)
        with self.engine.begin() as db:
            new_team = db.execute(text("INSERT INTO teams(name) VALUES ('New club') RETURNING id")).scalar_one()
            new_log = db.execute(text("INSERT INTO import_log(imported_at,matches,source) VALUES (now(),1,'x') RETURNING id")).scalar_one()
        self.assertGreater(new_team, max(self.team_ids.values()))
        self.assertEqual(new_log, 5)

    def test_refuses_non_empty_target(self):
        self.seed()
        with self.assertRaisesRegex(MigrationError, 'already contains data'):
            migrate(self.sqlite, self.engine, self.url)
        migrated = self.counts()
        self.assertEqual(migrated['import_log'], 1)

    def test_refuses_second_run(self):
        migrate(self.sqlite, self.engine, self.url)
        with self.assertRaisesRegex(MigrationError, 'already contains data'):
            migrate(self.sqlite, self.engine, self.url)

    def test_rejects_unexpected_sources(self):
        with self.assertRaisesRegex(MigrationError, 'not found'):
            migrate(Path(self.tmp.name) / 'missing.sqlite3', self.engine, self.url)
        import sqlite3
        other = Path(self.tmp.name) / 'other.sqlite3'
        sqlite3.connect(other).execute('PRAGMA user_version=7').connection.close()
        with self.assertRaisesRegex(MigrationError, 'Unsupported SQLite schema version 7'):
            migrate(other, self.engine, self.url)

    def test_compare_reports_count_total_and_content_mismatches(self):
        src = {'innings': {'rows': 2, 'totals': {'runs': 10}, 'digest': 'a'}}
        dst = {'innings': {'rows': 1, 'totals': {'runs': 9}, 'digest': 'b'}}
        problems = compare(src, dst)
        self.assertEqual(len(problems), 3)
        self.assertEqual(compare(src, src), [])
