"""PostgreSQL integration tests: migrations, seeding, analytics and imports."""
import json
import unittest

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app.analytics import coach, players, profile, summary
from app.db import alembic_config, make_engine, schema_status
from app.ingestion.scorecards import BUNDLED_SCORECARDS, import_bundle
from app.main import create_app
from app.models import Base
from tests.pg import PostgresTestCase, reset_schema, test_database_url, upgrade


def bundle():
    return json.loads(BUNDLED_SCORECARDS.read_text())


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = test_database_url()
        cls.engine = make_engine(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        reset_schema(self.engine)

    def tables(self):
        return set(inspect(self.engine).get_table_names()) - {'alembic_version'}

    def test_upgrade_matches_models_and_downgrade_rolls_back(self):
        self.assertEqual(schema_status(self.engine, self.url)[0], None)
        upgrade(self.url)
        current, head, ok = schema_status(self.engine, self.url)
        self.assertTrue(ok)
        self.assertEqual(self.tables(), set(Base.metadata.tables))
        with self.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={'compare_type': True,
                                                                            'compare_server_default': True}),
                                    Base.metadata)
        self.assertEqual(diff, [], 'models and migrations have diverged')
        command.downgrade(alembic_config(self.url), 'base')
        self.assertEqual(self.tables(), set())
        self.assertIsNone(schema_status(self.engine, self.url)[0])
        upgrade(self.url)
        self.assertEqual(self.tables(), set(Base.metadata.tables))

    def test_constraints_reject_invalid_cricket_rows(self):
        upgrade(self.url)
        with self.engine.begin() as db:
            db.execute(text("INSERT INTO teams(name) VALUES ('A'),('B')"))
        bad = ["INSERT INTO matches(id,date,venue,team1,team2,winner,result,source_url,retrieved_at) "
               "VALUES ('1','2026-01-01','v',1,1,1,'r','u','t')",
               "INSERT INTO matches(id,date,venue,team1,team2,winner,result,source_url,retrieved_at) "
               "VALUES ('1','2026-01-01','v',1,2,3,'r','u','t')"]
        for sql in bad:
            with self.subTest(sql), self.assertRaises(Exception):
                with self.engine.begin() as db:
                    db.execute(text(sql))

    def test_app_creation_does_not_migrate_or_seed(self):
        app = create_app(self.engine, ['testserver'], self.url)
        self.assertIsNotNone(app)
        self.assertEqual(self.tables(), set())
        upgrade(self.url)
        create_app(self.engine, ['testserver'], self.url)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM teams')).scalar_one(), 0)


class DataTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.db = self.engine.connect()

    def tearDown(self):
        self.db.close()

    def count(self, table):
        return self.db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()

    def test_seed_reconciles_with_snapshot(self):
        s = summary(self.db)
        self.assertEqual((s['completed'], s['recorded_runs'], len(s['teams']), s['roster_entries']), (5, 1923, 15, 915))
        balls = self.db.execute(text('SELECT sum(balls) FROM innings')).scalar_one()
        self.assertIsInstance(balls, int)

    def test_seed_is_idempotent_and_never_overwrites_corrections(self):
        before = {t: self.count(t) for t in ('teams', 'roster_entries', 'players', 'matches', 'batting', 'import_log')}
        corrected = bundle()
        corrected['matches'] = [corrected['matches'][0]]
        corrected['matches'][0]['venue'] = 'Corrected venue'
        with self.engine.begin() as db:
            import_bundle(db, corrected, 'correction')
        report = self.seed()
        self.assertEqual(report, {'club_listings_added': 0, 'matches_added': 0, 'matches_already_present': 5})
        self.db.rollback()
        self.assertEqual(self.db.execute(text("SELECT venue FROM matches WHERE id='27377965'")).scalar_one(), 'Corrected venue')
        after = {t: self.count(t) for t in before}
        self.assertEqual(after, dict(before, import_log=before['import_log'] + 1))

    def test_identity_and_metrics(self):
        p = profile(self.db, '32722355')
        self.assertEqual((p['runs'], p['balls'], p['innings']), (0, 4, 1))
        self.assertEqual(p['average'], 0)
        p = profile(self.db, '1936055')
        self.assertEqual(p['runs'], 180)
        self.assertEqual(p['strike_rate'], 225)
        self.assertIsNone(p['average'])
        p = profile(self.db, '27014853')
        self.assertEqual((p['wickets'], p['economy']), (7, 3))
        self.assertIsNone(profile(self.db, 'nobody'))
        self.assertIn('undefined because there are no dismissals', coach(self.db, '1936055', 'summary'))

    def test_team_scope(self):
        tid = self.db.execute(text("SELECT id FROM teams WHERE name='UTKAL Cricket Club (UCC).'")).scalar_one()
        s = summary(self.db, tid)
        self.assertEqual((s['recorded_runs'], s['completed']), (188, 1))
        self.assertTrue(all(tid in p['team_ids'] for p in players(self.db, tid)))

    def test_failed_import_keeps_old_scores(self):
        b = bundle()
        b['matches'][1]['innings'][0]['runs'] += 1
        with self.assertRaises(ValueError):
            with self.engine.begin() as db:
                import_bundle(db, b)
        self.db.rollback()
        self.assertEqual(summary(self.db)['recorded_runs'], 1923)
        self.assertEqual(self.count('import_log'), 1)

    def test_database_error_mid_import_rolls_back_everything(self):
        b = bundle()
        b['matches'][0]['venue'] = 'Should not persist'
        with self.assertRaises(Exception):
            with self.engine.begin() as db:
                import_bundle(db, b)
                db.execute(text('SELECT 1/0'))
        self.db.rollback()
        self.assertNotEqual(self.db.execute(text("SELECT venue FROM matches WHERE id='27377965'")).scalar_one(),
                            'Should not persist')

    def test_repeat_import_does_not_duplicate_statistics(self):
        with self.engine.begin() as db:
            import_bundle(db, bundle())
        self.db.rollback()
        self.assertEqual(summary(self.db)['completed'], 5)
        self.assertEqual(summary(self.db)['recorded_runs'], 1923)
        self.assertEqual(profile(self.db, '27014853')['wickets'], 7)
        self.assertEqual(self.count('import_log'), 2)


if __name__ == '__main__':
    unittest.main()
