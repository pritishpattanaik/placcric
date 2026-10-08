"""Captain's room match-ups, friendly matches and AI analysis with a mocked OpenRouter (no network)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import pin
from app.main import create_app
from app.matchup import credited_bowler, dismissal_type
from tests import pdf_fixture
from tests.pg import PostgresTestCase

PIN = '246810'
AI_ENV = {'OPENROUTER_API_KEY': 'sk-or-test-not-a-real-key', 'OPENROUTER_MODEL': 'test/model-x',
          'PLACCRIC_AI_DAILY_LIMIT': '5', 'PLACCRIC_AI_MAX_OUTPUT_TOKENS': '800'}


class DismissalParsingTests(unittest.TestCase):
    def test_types_and_credited_bowler(self):
        cases = {
            'c Harish Naidu b Rajesh Kharche (RK)': ('caught', 'Rajesh Kharche (RK)'),
            'lbw b Md. Anowar Zahid': ('lbw', 'Md. Anowar Zahid'),
            'b Sikandar Khan': ('bowled', 'Sikandar Khan'),
            'c&b Sagor Sheikh': ('caught and bowled', 'Sagor Sheikh'),
            'c & b Sagor Sheikh': ('caught and bowled', 'Sagor Sheikh'),
            'st †AU Mahi b Tanjirul Islam Taj': ('stumped', 'Tanjirul Islam Taj'),
            'c †Arifur rahman b Md Hafizur Rahman (Limon)': ('caught', 'Md Hafizur Rahman (Limon)'),
            'run out † Arifur rahman / Asif Hassan': ('run out', None),
            'not out': ('not out', None),
            'retired hurt': ('not out', None),
            '': ('unknown', None),
        }
        for text_, (kind, bowler) in cases.items():
            with self.subTest(text_):
                self.assertEqual((dismissal_type(text_), credited_bowler(text_)), (kind, bowler))


class FakeOpenRouter:
    def __init__(self, status=200, answer='## Summary\n- Bowl first.'):
        self.calls, self.status, self.answer = [], status, answer

    def __call__(self, request):
        self.calls.append({'headers': dict(request.headers), 'body': json.loads(request.content)})
        if self.status != 200:
            return httpx.Response(self.status, json={'error': {'message': 'Invalid credentials'}})
        return httpx.Response(200, json={'choices': [{'message': {'content': self.answer}}],
                                         'usage': {'prompt_tokens': 1234, 'completion_tokens': 210}})


class CaptainAndAiTests(PostgresTestCase):
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
            self.ucc = db.execute(text("SELECT id FROM teams WHERE name='UTKAL Cricket Club (UCC).'")).scalar()
            self.cyber = db.execute(text("SELECT id FROM teams WHERE name='Cyber XI'")).scalar()
            self.friendly = db.execute(text("SELECT id FROM tournaments WHERE kind='friendly'")).scalar()
        self.uploads = tempfile.TemporaryDirectory()
        self.fake = FakeOpenRouter()
        self.client = TestClient(create_app(self.engine, ['testserver'], self.url, upload_dir=self.uploads.name,
                                            ai_transport=httpx.MockTransport(self.fake)))
        self.csrf = self.client.post('/api/login', json={'pin': PIN}).json()['csrf']

    def tearDown(self):
        self.uploads.cleanup()

    def post(self, path, body):
        return self.client.post(path, json=body, headers={'X-CSRF-Token': self.csrf})

    def analyze(self, **body):
        return self.post('/api/ai/analyze', {'kind': 'matchup', 'team': self.ucc, 'opponent': self.cyber, **body})

    # Captain's room
    def test_matchup_report_is_built_from_scorecards(self):
        r = self.client.get(f'/api/captain/matchup?team={self.ucc}&opponent={self.cyber}').json()
        self.assertEqual((r['team']['team'], r['opponent']['team']), ('UTKAL Cricket Club (UCC).', 'Cyber XI'))
        self.assertEqual((r['team']['matches'], r['team']['won'], r['team']['lost']), (1, 0, 1))
        self.assertEqual(r['team']['batting_first'], {'played': 1, 'won': 0})
        self.assertEqual(r['team']['average_score'], 188.0)
        self.assertEqual(r['team']['run_rate'], 7.52)
        self.assertTrue(r['team']['small_sample'])
        self.assertEqual(len(r['head_to_head']), 1)
        self.assertEqual(r['head_to_head'][0]['winner'], 'Cyber XI')
        h2h = r['dismissals']['head_to_head_dismissals']
        self.assertIn({'bowler': 'Rajesh Kharche (RK)', 'bowler_team': 'Cyber XI', 'batter': 'Pritish Pattanaik',
                       'times': 1}, h2h)
        out = r['dismissals']['how_batters_get_out']['UTKAL Cricket Club (UCC).']
        self.assertEqual(sum(out.values()), 9)
        self.assertTrue(any('ball-by-ball' in l for l in r['data_limits']))
        self.assertEqual(r['their_batters'][0]['name'], max(r['their_batters'], key=lambda p: p['runs'])['name'])

    def test_matchup_validation(self):
        self.assertEqual(self.client.get(f'/api/captain/matchup?team={self.ucc}&opponent={self.ucc}').status_code, 400)
        self.assertEqual(self.client.get(f'/api/captain/matchup?team={self.ucc}&opponent=999999').status_code, 400)
        self.assertEqual(self.client.get(f'/api/captain/matchup?team={self.ucc}').status_code, 400)
        anon = TestClient(create_app(self.engine, ['testserver'], self.url))
        self.assertEqual(anon.get(f'/api/captain/matchup?team={self.ucc}&opponent={self.cyber}').status_code, 401)

    # Friendly matches
    def test_friendly_category_accepts_any_pdf_without_title_warning(self):
        r = self.client.post(f'/api/imports?tournament={self.friendly}', content=pdf_fixture.scorecard_pdf(),
                             headers={'Content-Type': 'application/pdf', 'X-CSRF-Token': self.csrf,
                                      'X-Filename': 'Scorecard_99000001.pdf'})
        batch = r.json()['batch_id']
        preview = self.client.get(f'/api/imports/{batch}').json()
        self.assertEqual(preview['warnings'], [])
        self.assertEqual(preview['rules'], {'overs_per_innings': 50, 'max_overs_per_bowler': 50})
        self.assertEqual(self.post(f'/api/imports/{batch}/approve', {}).status_code, 200)
        tours = {t['name']: t for t in self.client.get('/api/tournaments').json()}
        self.assertEqual((tours['Friendly Match']['kind'], tours['Friendly Match']['matches']), ('friendly', 1))
        s = self.client.get(f'/api/summary?tournament={self.friendly}').json()
        self.assertEqual((s['completed'], s['recorded_runs']), (1, 220))

    # AI
    def test_ai_is_off_until_configured_and_makes_no_call(self):
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': '', 'OPENROUTER_MODEL': ''}):
            st = self.client.get('/api/ai/status').json()
            self.assertEqual((st['configured'], st['missing']), (False, ['OPENROUTER_API_KEY', 'OPENROUTER_MODEL']))
            r = self.analyze()
        self.assertEqual(r.status_code, 503)
        self.assertIn('OPENROUTER_API_KEY', r.json()['error'])
        self.assertEqual(self.fake.calls, [])

    def test_matchup_analysis_sends_only_the_evidence_and_is_cached(self):
        with mock.patch.dict(os.environ, AI_ENV):
            self.assertEqual(self.client.post('/api/ai/analyze', json={'kind': 'matchup'}).status_code, 403)
            st = self.client.get('/api/ai/status').json()
            self.assertEqual((st['configured'], st['model'], st['daily_limit']), (True, 'test/model-x', 5))
            self.assertNotIn('sk-or', json.dumps(st))
            r = self.analyze(question='We bat first on a slow pitch')
            self.assertEqual(r.status_code, 200, r.text)
            d = r.json()
            self.assertEqual((d['answer'], d['cached'], d['model'], d['prompt_tokens']), ('## Summary\n- Bowl first.', False, 'test/model-x', 1234))
            self.assertEqual(d['subject'], 'UTKAL Cricket Club (UCC). vs Cyber XI')
            call = self.fake.calls[0]
            self.assertEqual(call['headers']['authorization'], 'Bearer sk-or-test-not-a-real-key')
            self.assertEqual((call['body']['model'], call['body']['max_tokens']), ('test/model-x', 800))
            sent = json.dumps(call['body'])
            self.assertIn('Use ONLY the JSON evidence', sent)
            self.assertIn('We bat first on a slow pitch', sent)
            self.assertIn('Pritish Pattanaik', sent)
            for private in ('32722355', '27377965', PIN, 'our_match_plan_notes'):
                self.assertNotIn(private, sent, private)
            # Identical request: served from the cache, no second call.
            again = self.analyze(question='We bat first on a slow pitch').json()
            self.assertTrue(again['cached'])
            self.assertEqual(len(self.fake.calls), 1)
            # Refresh forces a new call.
            self.assertFalse(self.analyze(question='We bat first on a slow pitch', refresh=True).json()['cached'])
            self.assertEqual(len(self.fake.calls), 2)
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT status, model, prompt_tokens, completion_tokens FROM ai_requests')).all()
        self.assertEqual([tuple(r) for r in rows], [('ok', 'test/model-x', 1234, 210)] * 2)

    def test_notes_are_sent_only_when_included(self):
        self.post('/api/notes', {'team': self.ucc, 'body': 'Open with spin from the school end'})
        with mock.patch.dict(os.environ, AI_ENV):
            self.analyze(include_notes=True)
        sent = json.dumps(self.fake.calls[0]['body'])
        self.assertIn('Open with spin from the school end', sent)

    def test_player_and_compare_analyses(self):
        with mock.patch.dict(os.environ, AI_ENV):
            r = self.post('/api/ai/analyze', {'kind': 'player', 'player_id': '32722355'})
            self.assertEqual((r.status_code, r.json()['subject']), (200, 'Pritish Pattanaik'))
            self.assertIn('scouting report on Pritish Pattanaik', json.dumps(self.fake.calls[-1]['body']))
            r = self.post('/api/ai/analyze', {'kind': 'compare', 'player_ids': ['1936055', '27014853']})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(r.json()['evidence']['players']), 2)
            self.assertEqual(self.post('/api/ai/analyze', {'kind': 'player', 'player_id': 'nobody'}).status_code, 404)
            self.assertEqual(self.post('/api/ai/analyze', {'kind': 'compare', 'player_ids': ['1']}).status_code, 400)
            self.assertEqual(self.post('/api/ai/analyze', {'kind': 'other'}).status_code, 400)
            self.assertEqual(self.analyze(question='x' * 1001).status_code, 400)

    def test_provider_errors_and_daily_limit(self):
        self.fake.status = 401
        with mock.patch.dict(os.environ, AI_ENV):
            r = self.analyze()
            self.assertEqual(r.status_code, 502)
            self.assertEqual(r.json()['error'], 'OpenRouter returned 401: Invalid credentials')
            self.assertNotIn('sk-or', r.text)
        self.fake.status = 200
        with mock.patch.dict(os.environ, {**AI_ENV, 'PLACCRIC_AI_DAILY_LIMIT': '2'}):
            self.assertEqual(self.analyze(question='a').status_code, 200)
            r = self.analyze(question='b')
            self.assertEqual(r.status_code, 502)
            self.assertIn('daily AI limit (2 requests)', r.json()['error'])
            self.assertEqual(self.analyze(question='a').json()['cached'], True, 'cached answers still work')
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM ai_requests WHERE status='error'")).scalar(), 1)
