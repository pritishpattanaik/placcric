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


BRIEFS = {
    'Tactical brief': {'headline': 'Bowl first and attack early', 'confidence': 'LOW',
                       'pivot_points': [{'title': 'Collapse', 'insight': 'They lost 4 for 11', 'evidence': '164/6 to 175/10'}],
                       'threats': [{'player': 'Feroz Ahmad', 'team': 'Cyber XI', 'threat': 'Top scorer', 'evidence': '1 innings'}],
                       'matchups': [], 'blueprint': {'batting': ['See off the new ball'], 'bowling': [], 'field': []},
                       'data_gaps': ['Only 1 match'], 'unexpected_field': 'dropped'},
    'Performance diagnosis': {'headline': 'Early dismissals', 'confidence': 'low', 'role': 'Top order',
                              'answer': 'Spend longer at the crease early.',
                              'patterns': [{'label': 'Strike rate', 'value': '0.0', 'insight': 'x' * 500}],
                              'diagnosis': [{'area': 'Shot selection', 'finding': 'Caught early', 'evidence': '0 (4)'}],
                              'drills': [{'name': 'First 10 balls', 'focus': 'Survival', 'detail': 'Leave and defend'}],
                              'strengths': [], 'data_gaps': []},
    'Selection comparison': {'headline': 'Different roles', 'confidence': 'medium',
                             'verdicts': [{'situation': 'Chasing', 'pick': 'A', 'reason': 'Higher strike rate'}],
                             'edges': [{'metric': 'Strike rate', 'edge': 'A', 'note': '225 vs 100'}], 'data_gaps': []},
    'post-match debrief': {'headline': 'Chase built on the top order', 'confidence': 'medium', 'turning_points': [],
                           'team_reviews': [{'team': 'Cyber XI', 'went_well': ['Chase'], 'to_improve': []}],
                           'standouts': [], 'data_gaps': []},
}


class FakeOpenRouter:
    """Mimics a 'thinking' model: reasoning text, a draft object, then the final JSON."""

    def __init__(self, status=200, content=None):
        self.calls, self.status, self.content = [], status, content

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append({'headers': dict(request.headers), 'body': body})
        if self.status != 200:
            return httpx.Response(self.status, json={'error': {'message': 'Invalid credentials'}})
        task = body['messages'][1]['content']
        brief = next(v for k, v in BRIEFS.items() if k in task)
        content = self.content if self.content is not None else (
            "Here's a thinking process:\n1. Analyze {request}. Draft: {\"headline\": 1}\n```json\n"
            + json.dumps(brief) + '\n```')
        return httpx.Response(200, json={'choices': [{'message': {'content': content}}],
                                         'usage': {'prompt_tokens': 1234, 'completion_tokens': 210}})


class _AiBase(PostgresTestCase):
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


class CaptainAndAiTests(_AiBase):

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
            self.assertEqual((d['cached'], d['model'], d['prompt_tokens']), (False, 'test/model-x', 1234))
            brief = d['brief']
            self.assertEqual((brief['headline'], brief['confidence']), ('Bowl first and attack early', 'low'))
            self.assertNotIn('unexpected_field', brief)
            self.assertEqual(brief['blueprint'], {'batting': ['See off the new ball'], 'bowling': [], 'field': []})
            self.assertNotIn('thinking', json.dumps(brief))
            self.assertEqual(d['subject'], 'UTKAL Cricket Club (UCC). vs Cyber XI')
            call = self.fake.calls[0]
            self.assertEqual(call['headers']['authorization'], 'Bearer sk-or-test-not-a-real-key')
            self.assertEqual((call['body']['model'], call['body']['max_tokens']), ('test/model-x', 800))
            sent = json.dumps(call['body'])
            self.assertIn('Use ONLY the JSON evidence', sent)
            self.assertEqual(call['body']['response_format'], {'type': 'json_object'})
            self.assertIn('pivots', sent)
            self.assertIn('We bat first on a slow pitch', sent)
            self.assertIn('Pritish Pattanaik', sent)
            for private in ('32722355', '27377965', PIN, 'our_match_plan_notes'):
                self.assertNotIn(private, sent, private)
            # Identical request: served from the cache, no second call.
            again = self.analyze(question='We bat first on a slow pitch').json()
            self.assertTrue(again['cached'])
            self.assertEqual(again['brief'], brief)
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
            self.assertIn('Performance diagnosis for Pritish Pattanaik', json.dumps(self.fake.calls[-1]['body']))
            b = r.json()['brief']
            self.assertEqual((b['diagnosis'][0]['area'], b['answer']), ('shot selection', 'Spend longer at the crease early.'))
            self.assertLessEqual(len(b['patterns'][0]['insight']), 160)
            r = self.post('/api/ai/analyze', {'kind': 'compare', 'player_ids': ['1936055', '27014853']})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(r.json()['evidence']['players']), 2)
            self.assertEqual(r.json()['brief']['verdicts'][0]['pick'], 'A')
            self.assertIn('Player A is Arifur Rahman', json.dumps(self.fake.calls[-1]['body']))
            r = self.post('/api/ai/analyze', {'kind': 'debrief', 'match_id': '27377965'})
            self.assertEqual((r.status_code, r.json()['brief']['headline']), (200, 'Chase built on the top order'))
            self.assertEqual(self.post('/api/ai/analyze', {'kind': 'debrief', 'match_id': '0'}).status_code, 404)
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


    def test_unusable_model_output_is_rejected_not_shown(self):
        for content in ('Just some prose without JSON.', '{"headline": "x", "confidence": "certain"}',
                        '{"confidence": "low"}'):
            with self.subTest(content):
                self.fake.content = content
                with mock.patch.dict(os.environ, AI_ENV):
                    r = self.analyze(question=content)
                self.assertEqual(r.status_code, 502)
                self.assertIn('did not return a usable brief', r.json()['error'])
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM ai_requests WHERE status='ok'")).scalar(), 0)


class BriefExtractionTests(unittest.TestCase):
    def test_takes_the_last_valid_object_and_clips_fields(self):
        from app.ai.briefs import BriefError, extract
        draft = '{"headline": "draft", "confidence": "nope"}'
        final = json.dumps({'headline': 'H' * 300, 'confidence': 'High', 'verdicts': [{'situation': 's', 'pick': 'b',
                                                                                         'reason': 'r'}] * 9})
        b = extract('compare', f'thinking... {draft} more thinking {final} trailing')
        self.assertEqual((len(b['headline']), b['confidence'], len(b['verdicts']), b['verdicts'][0]['pick']),
                         (140, 'high', 5, 'B'))
        with self.assertRaises(BriefError):
            extract('compare', draft)


class PivotAndCompareTests(_AiBase):
    """Runs on the synthetic PDF (invented players), whose fall of wickets is known exactly."""

    def setUp(self):
        super().setUp()
        r = self.client.post(f'/api/imports?tournament={self.friendly}', content=pdf_fixture.scorecard_pdf(),
                             headers={'Content-Type': 'application/pdf', 'X-CSRF-Token': self.csrf,
                                      'X-Filename': 'Scorecard_99000001.pdf'})
        self.assertEqual(self.post(f"/api/imports/{r.json()['batch_id']}/approve", {}).status_code, 200)
        with self.engine.connect() as db:
            self.alpha = db.execute(text("SELECT id FROM teams WHERE name='Alpha Strikers XI'")).scalar()
            self.beta = db.execute(text("SELECT id FROM teams WHERE name='Beta Royals CC'")).scalar()

    def test_fall_of_wickets_is_stored_and_shown_in_revisions(self):
        with self.engine.connect() as db:
            rows = db.execute(text("SELECT innings_number, count(*), max(runs) FROM fall_of_wickets "
                                   "WHERE match_id='99000001' GROUP BY 1 ORDER BY 1")).all()
        self.assertEqual([tuple(r) for r in rows], [(1, 5, 112), (2, 9, 99)])
        s = pdf_fixture.spec()
        s['innings'][0]['fow'][4] = (113, 5, 'Eli Five', '18.4')
        r = self.client.post(f'/api/imports?tournament={self.friendly}', content=pdf_fixture.scorecard_pdf(s),
                             headers={'Content-Type': 'application/pdf', 'X-CSRF-Token': self.csrf,
                                      'X-Filename': 'Scorecard_99000001.pdf'})
        m = self.client.get(f"/api/imports/{r.json()['batch_id']}").json()['matches'][0]
        self.assertEqual(m['status'], 'correction')
        self.assertEqual([c['field'] for c in m['changes']], ['Innings 1 fall of wickets'])

    def test_pivot_points(self):
        r = self.client.get(f'/api/captain/matchup?team={self.alpha}&opponent={self.beta}').json()
        alpha, beta = r['pivots']['team'], r['pivots']['opponent']
        self.assertEqual((alpha['innings_with_fall_of_wickets'], alpha['innings_total']), (1, 1))
        self.assertEqual(alpha['wickets_by_phase'], {'Overs 1–6': 0, 'Overs 7–15': 4, 'Overs 16+': 1})
        self.assertEqual(beta['wickets_by_phase'], {'Overs 1–6': 1, 'Overs 7–15': 4, 'Overs 16+': 4})
        self.assertEqual([(c['from'], c['to'], c['wickets'], c['runs']) for c in alpha['collapses']], [('55/0', '64/3', 3, 9)])
        self.assertEqual([(c['from'], c['to']) for c in beta['collapses']], [('70/2', '84/5'), ('88/5', '99/9')])
        self.assertEqual([(c['from'], c['to']) for c in alpha['collapses_caused_with_ball']], [('70/2', '84/5'), ('88/5', '99/9')])
        self.assertEqual(alpha['best_partnership'], {'wicket': 1, 'runs': 55, 'balls': 38, 'against': 'Beta Royals CC',
                                                     'date': '2026-01-02'})
        self.assertEqual(alpha['timelines'][0]['fow'][-1], {'wicket': 5, 'runs': 112, 'balls': 111, 'batter': 'Eli Five'})
        self.assertEqual(alpha['timelines'][0]['max_balls'], 300)

    def test_compare_cards(self):
        with self.engine.connect() as db:
            ann = db.execute(text("SELECT id FROM players WHERE name='Ann One'")).scalar()
            jo = db.execute(text("SELECT id FROM players WHERE name='Jo Ten'")).scalar()
        r = self.client.get(f'/api/compare?a={ann}&b={jo}').json()
        self.assertEqual((r['a']['batting_role'], r['a']['dismissal_types'], r['a']['runs']), ('Opener', {'caught': 1}, 40))
        self.assertEqual((r['b']['wickets'], r['b']['dot_ball_pct'], r['b']['batting_role']), (2, 41.7, 'Opener'))
        self.assertEqual(len(r['a']['innings_series']), 1)
        self.assertEqual(self.client.get(f'/api/compare?a={ann}&b=nobody').status_code, 404)
