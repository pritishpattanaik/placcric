"""Staged imports end to end over HTTP: upload → preview → approve/reject, identities, revisions, restore."""
import json
import os
import stat
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import pin
from app.ingestion.scorecards import BUNDLED_SCORECARDS
from app.main import create_app
from tests import pdf_fixture
from tests.pg import PostgresTestCase

PIN = '246810'
T20 = {'name': 'Test League T20 Season 1', 'external_id': '5550001', 'slug': 'test-league-t20-season-1',
       'overs_per_innings': 20, 'max_overs_per_bowler': 4}


class ImportTests(PostgresTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.iterations, pin.ITERATIONS = pin.ITERATIONS, 1000

    @classmethod
    def tearDownClass(cls):
        pin.ITERATIONS = cls.iterations
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.seed()
        with self.engine.begin() as db:
            pin.set_pin(db, PIN)
        self.uploads = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(self.engine, ['testserver'], self.url, upload_dir=self.uploads.name))
        self.csrf = self.client.post('/api/login', json={'pin': PIN}).json()['csrf']
        r = self.post('/api/tournaments', T20)
        self.assertEqual(r.status_code, 200, r.text)
        self.tournament = r.json()['id']

    def tearDown(self):
        self.uploads.cleanup()

    # helpers
    def post(self, path, body):
        return self.client.post(path, json=body, headers={'X-CSRF-Token': self.csrf})

    def upload(self, data, filename='Scorecard_99000001.pdf', kind='application/pdf', tournament=None, **params):
        query = '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.post(f'/api/imports?tournament={tournament or self.tournament}&{query}', content=data,
                                headers={'Content-Type': kind, 'X-CSRF-Token': self.csrf, 'X-Filename': filename})

    def staged(self, data=None, **kw):
        r = self.upload(data or pdf_fixture.scorecard_pdf(), **kw)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['batch_id']

    def preview(self, batch):
        r = self.client.get(f'/api/imports/{batch}')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def approve(self, batch, decisions=None, status=200):
        r = self.post(f'/api/imports/{batch}/approve', {'decisions': decisions or {}})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def scalar(self, sql, **args):
        with self.engine.connect() as db:
            return db.execute(text(sql), args).scalar()

    def summary(self, tournament=None):
        return self.client.get('/api/summary' + (f'?tournament={tournament}' if tournament else '')).json()

    # tests
    def test_upload_requires_admin_session_and_csrf(self):
        anon = TestClient(create_app(self.engine, ['testserver'], self.url, upload_dir=self.uploads.name))
        r = anon.post(f'/api/imports?tournament={self.tournament}', content=pdf_fixture.scorecard_pdf(),
                      headers={'Content-Type': 'application/pdf'})
        self.assertEqual(r.status_code, 401)
        r = self.client.post(f'/api/imports?tournament={self.tournament}', content=pdf_fixture.scorecard_pdf(),
                             headers={'Content-Type': 'application/pdf'})
        self.assertEqual(r.status_code, 403)
        batch = self.staged()
        for path in (f'/api/imports/{batch}/approve', f'/api/imports/{batch}/reject', '/api/tournaments'):
            self.assertEqual(self.client.post(path, json={}).status_code, 403, path)
        self.assertEqual(anon.get(f'/api/imports/{batch}').status_code, 401)

    def test_upload_validation(self):
        self.assertEqual(self.upload(b'hello', kind='text/plain').status_code, 415)
        r = self.upload(b'not a pdf at all')
        self.assertEqual((r.status_code, r.json()['error']), (400, 'That file is not a PDF.'))
        self.assertEqual(self.upload(b'%PDF-' + b'0' * 10_000_001).status_code, 413)
        r = self.upload(pdf_fixture.scorecard_pdf(), filename='scorecard.pdf')
        self.assertIn('Enter the CricHeroes match ID', r.json()['error'])
        self.assertEqual(self.upload(pdf_fixture.scorecard_pdf(), tournament=999999).status_code, 400)
        r = self.upload(b'{"matches": []}', filename='x.json', kind='application/json')
        self.assertIn('not in the scorecard format', r.json()['error'])
        self.assertEqual(self.scalar('SELECT count(*) FROM import_batches'), 0)

    def test_pdf_is_staged_previewed_and_published_only_on_approval(self):
        before = self.summary()
        batch = self.staged()
        p = self.preview(batch)
        self.assertEqual((p['status'], p['kind'], p['filename'], p['approvable']), ('staged', 'pdf', 'Scorecard_99000001.pdf', True))
        self.assertEqual(p['errors'], [])
        m = p['matches'][0]
        self.assertEqual((m['id'], m['status'], m['stage']), ('99000001', 'new', 'Final'))
        self.assertEqual([(i['runs'], i['wickets'], i['overs']) for i in m['innings']], [(120, 5, '20.0'), (100, 9, '20.0')])
        self.assertEqual(len(m['identities']), 17)  # 16 batters + 1 bowler who did not bat
        self.assertTrue(all(i['status'] == 'unresolved' and not i['requires_choice'] for i in m['identities']))
        self.assertEqual(self.summary()['completed'], before['completed'], 'staging must not publish')

        out = self.approve(batch)['outcome']
        self.assertEqual(out, [{'match_id': '99000001', 'result': 'published', 'revision': 1}])
        s = self.summary(self.tournament)
        self.assertEqual((s['completed'], s['recorded_runs']), (1, 220))
        self.assertEqual(self.summary()['completed'], before['completed'] + 1)
        self.assertEqual(self.summary(self.tournament)['teams'][0]['name'], 'Alpha Strikers XI')
        self.assertEqual(self.scalar("SELECT count(*) FROM players WHERE provider='placcric'"), 17)
        self.assertEqual(self.scalar('SELECT count(*) FROM player_aliases'), 17)
        match = self.client.get('/api/matches/99000001').json()
        self.assertEqual((match['stage'], match['tournament_name']), ('Final', 'Test League T20 Season 1'))
        ann = next(b for b in match['innings'][0]['batting'] if b['name'] == 'Ann One')
        profile = self.client.get(f'/api/players/{ann["player_id"]}').json()
        self.assertEqual((profile['runs'], profile['source_url']), (40, None))
        self.assertEqual(self.preview(batch)['status'], 'approved')
        self.approve(batch, status=400)

    def test_raw_upload_is_private_and_deduplicated(self):
        data = pdf_fixture.scorecard_pdf()
        batch = self.staged(data)
        p = self.preview(batch)
        stored = Path(self.uploads.name) / f'{p["file_sha256"]}.pdf'
        self.assertEqual(stored.read_bytes(), data)
        self.assertEqual(stat.S_IMODE(os.stat(stored).st_mode), 0o600)
        again = self.upload(data, filename='renamed.pdf', match_id='99000001').json()
        self.assertEqual(again, {'batch_id': batch, 'already_uploaded': True})

    def test_identical_reimport_is_a_no_op_and_corrections_create_revisions(self):
        self.approve(self.staged())
        runs_before = self.summary(self.tournament)['recorded_runs']
        # Same scores, re-downloaded later (different file bytes): nothing changes.
        pages = pdf_fixture.lines_for(pdf_fixture.MATCH)
        pages[0][-1] = pages[0][-1].replace('9:00 AM', '9:30 AM')
        batch = self.staged(pdf_fixture.build_pdf(pages))
        m = self.preview(batch)['matches'][0]
        self.assertEqual(m['status'], 'unchanged')
        self.assertTrue(all(i['status'] == 'confirmed' for i in m['identities']))
        self.assertEqual(self.approve(batch)['outcome'], [{'match_id': '99000001', 'result': 'unchanged'}])
        self.assertEqual(len(self.client.get('/api/matches/99000001/revisions').json()), 1)

        # A correction: Ann One 40 → 42 and two fewer wides.
        s = pdf_fixture.spec()
        s['innings'][0]['batting'][0] = ('Ann One (RHB)', 'c Ian Nine b Jo Ten', 42, 30, 4, 1)
        s['innings'][0].update(extras=10, extras_text='wd 3, nb 1, b 4, lb 2')
        s['innings'][0]['bowling'][0] = ('Jo Ten', '4', 25, 2, 10, 0, 0)
        batch = self.staged(pdf_fixture.scorecard_pdf(s))
        m = self.preview(batch)['matches'][0]
        self.assertEqual(m['status'], 'correction')
        changes = {c['field']: (c['old'], c['new']) for c in m['changes']}
        self.assertEqual(changes, {'Innings 1 extras': (12, 10), 'Innings 1 batting: Ann One runs': (40, 42),
                                   'Innings 1 bowling: Jo Ten wides': (2, 0)})
        self.assertEqual(self.approve(batch)['outcome'][0]['revision'], 2)
        self.assertEqual(self.summary(self.tournament)['recorded_runs'], runs_before)
        ann = self.scalar("SELECT b.runs FROM batting b JOIN players p ON p.id=b.player_id WHERE p.name='Ann One'")
        self.assertEqual(ann, 42)

        # Restore revision 1 as revision 3.
        r = self.post('/api/matches/99000001/restore', {'revision': 1}).json()
        self.assertEqual(r, {'revision': 3, 'unchanged': False})
        self.assertEqual(self.scalar("SELECT b.runs FROM batting b JOIN players p ON p.id=b.player_id WHERE p.name='Ann One'"), 40)
        revs = self.client.get('/api/matches/99000001/revisions').json()
        self.assertEqual([(v['number'], v['current'], v['note']) for v in revs][0], (3, True, 'Restored revision 1'))
        self.assertEqual(self.post('/api/matches/99000001/restore', {'revision': 3}).json()['unchanged'], True)
        self.assertEqual(self.post('/api/matches/99000001/restore', {'revision': 9}).status_code, 404)

    def test_rejected_import_changes_nothing(self):
        batch = self.staged()
        self.assertEqual(self.post(f'/api/imports/{batch}/reject', {}).json(), {'ok': True})
        self.assertEqual(self.preview(batch)['status'], 'rejected')
        self.approve(batch, status=400)
        self.assertEqual(self.scalar("SELECT count(*) FROM matches WHERE id='99000001'"), 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM player_aliases'), 0)
        # A rejected file can be uploaded again as a fresh batch.
        self.assertNotEqual(self.staged(), batch)

    def test_errors_block_approval(self):
        s = pdf_fixture.spec()
        s['innings'][0]['batting'][0] = ('Ann One (RHB)', 'c Ian Nine b Jo Ten', 41, 30, 4, 1)
        batch = self.staged(pdf_fixture.scorecard_pdf(s))
        p = self.preview(batch)
        self.assertFalse(p['approvable'])
        self.assertIn('batting runs 109 + extras 12 ≠ total 120', p['errors'][0])
        self.assertIn('Fix the listed errors', self.approve(batch, status=400)['error'])
        tie = self.staged(pdf_fixture.scorecard_pdf(pdf_fixture.spec(result='Match tied')), match_id='99000002')
        self.assertTrue(any('ties, no-results' in e for e in self.preview(tie)['errors']))

    def test_tournament_rules_and_title_check(self):
        with self.engine.begin() as db:
            t25 = db.execute(text("SELECT id FROM tournaments WHERE external_id='2194193'")).scalar()
        batch = self.staged(tournament=t25)
        p = self.preview(batch)
        self.assertEqual(p['rules'], {'overs_per_innings': 25, 'max_overs_per_bowler': 5})
        self.assertTrue(any('The PDF says "TEST LEAGUE T20 SEASON 1"' in w for w in p['warnings']))
        self.approve(batch)
        other = self.staged(pdf_fixture.scorecard_pdf(pdf_fixture.spec(title='TEST LEAGUE T20 SEASON 1 (Semi Final)')))
        self.assertIn('already published in a different tournament', self.preview(other)['errors'][0])

    def test_names_need_explicit_decisions_and_links_are_remembered(self):
        self.approve(self.staged())
        ann_id = self.scalar("SELECT id FROM players WHERE name='Ann One'")
        # Next match: one name is spelled differently, one player is new.
        s = pdf_fixture.spec()
        s['innings'][0]['batting'][0] = ('Anne One (RHB)', 'c Ian Nine b Jo Ten', 40, 30, 4, 1)
        s['innings'][0]['batting'][5] = ('Zed Newman (RHB)', 'not out', 3, 5, 0, 0)
        batch = self.staged(pdf_fixture.scorecard_pdf(s), match_id='99000002')
        idents = {i['name']: i for i in self.preview(batch)['matches'][0]['identities'] if i['status'] == 'unresolved'}
        self.assertEqual(set(idents), {'Anne One', 'Zed Newman'})
        anne = idents['Anne One']
        self.assertTrue(anne['requires_choice'])
        self.assertEqual(anne['suggestions'][0]['id'], ann_id)
        self.assertFalse(idents['Zed Newman']['requires_choice'])
        err = self.approve(batch, status=400)['error']
        self.assertIn('Decide who "Anne One" (Alpha Strikers XI) is', err)
        self.assertEqual(self.scalar("SELECT count(*) FROM matches WHERE id='99000002'"), 0)
        bad = self.approve(batch, {anne['key']: {'action': 'link', 'player_id': 'nobody'}}, status=400)
        self.assertIn('Choose an existing player for Anne One', bad['error'])
        self.assertEqual(self.scalar("SELECT count(*) FROM players WHERE name='Zed Newman'"), 0, 'failed approval is atomic')
        self.approve(batch, {anne['key']: {'action': 'link', 'player_id': ann_id},
                             idents['Zed Newman']['key']: {'action': 'new', 'cricheroes_id': '77777777'}})
        profile = self.client.get(f'/api/players/{ann_id}').json()
        self.assertEqual((profile['runs'], profile['matches'], profile['name']), (80, 2, 'Ann One'))
        self.assertEqual(self.scalar("SELECT provider FROM players WHERE id='77777777'"), 'cricheroes')
        # The confirmed spelling now resolves by itself in a later import.
        third = self.staged(pdf_fixture.scorecard_pdf(s), match_id='99000003')
        self.assertTrue(all(i['status'] == 'confirmed' for i in self.preview(third)['matches'][0]['identities']))

    def test_json_bundle_goes_through_staging(self):
        with self.engine.begin() as db:
            t25 = db.execute(text("SELECT id FROM tournaments WHERE external_id='2194193'")).scalar()
        bundle = json.loads(BUNDLED_SCORECARDS.read_text())
        batch = self.staged(json.dumps(bundle).encode(), filename='scorecards.json', kind='application/json', tournament=t25)
        p = self.preview(batch)
        self.assertEqual([m['status'] for m in p['matches']], ['unchanged'] * 5)
        self.assertEqual({o['result'] for o in self.approve(batch)['outcome']}, {'unchanged'})
        bundle['matches'][0]['venue'] = 'Corrected ground'
        batch = self.staged(json.dumps(bundle).encode(), filename='fix.json', kind='application/json', tournament=t25)
        p = self.preview(batch)
        self.assertEqual([m['status'] for m in p['matches']], ['correction'] + ['unchanged'] * 4)
        self.assertEqual(p['matches'][0]['changes'], [{'field': 'venue', 'old': 'Kajang High School, Kuala Lumpur',
                                                       'new': 'Corrected ground'}])
        # Simulate data published before revisions existed (e.g. migrated from SQLite).
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM match_revisions WHERE match_id='27377965'"))
        out = self.approve(batch)['outcome']
        # A baseline revision of the current data is saved first, so the correction is revision 2.
        self.assertEqual(out[0], {'match_id': '27377965', 'result': 'published', 'revision': 2})
        revs = self.client.get('/api/matches/27377965/revisions').json()
        self.assertEqual(revs[-1]['note'], 'Baseline: data published before revisions')
        self.post('/api/matches/27377965/restore', {'revision': 1})
        self.assertEqual(self.client.get('/api/matches/27377965').json()['venue'], 'Kajang High School, Kuala Lumpur')

    def test_tournament_creation_validation(self):
        self.assertEqual(self.post('/api/tournaments', T20).status_code, 400)
        for bad in ({**T20, 'name': 'X'}, {**T20, 'name': 'Other', 'external_id': 'abc'},
                    {**T20, 'name': 'Other', 'external_id': '', 'max_overs_per_bowler': 30},
                    {**T20, 'name': 'Other', 'external_id': '', 'slug': 'Bad Slug'}):
            self.assertEqual(self.post('/api/tournaments', bad).status_code, 400, bad)
        names = [t['name'] for t in self.client.get('/api/tournaments').json()]
        self.assertEqual(sorted(names), sorted(['Diwhyn Choice T25 Cricket Carnival — Season 2', T20['name']]))
        self.assertEqual(self.client.get('/api/summary?tournament=abc').status_code, 400)
