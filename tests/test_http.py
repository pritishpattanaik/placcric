"""HTTP integration tests through FastAPI's TestClient against PostgreSQL."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import pin
from app.ingestion.scorecards import BUNDLED_SCORECARDS
from app.main import create_app
from tests.pg import PostgresTestCase

PIN = '246810'


class HttpTests(PostgresTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.iterations, pin.ITERATIONS = pin.ITERATIONS, 1000  # keep hashing fast in tests only

    @classmethod
    def tearDownClass(cls):
        pin.ITERATIONS = cls.iterations
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.seed()
        with self.engine.begin() as db:
            pin.set_pin(db, PIN)
        self.client = TestClient(create_app(self.engine, ['testserver'], self.url))

    def login(self, client=None):
        r = (client or self.client).post('/api/login', json={'pin': PIN})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['csrf']

    def post(self, path, body, csrf):
        return self.client.post(path, json=body, headers={'X-CSRF-Token': csrf})

    def test_static_assets_and_security_headers(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r.headers['content-type'])
        for h in ('content-security-policy', 'x-frame-options', 'x-content-type-options', 'referrer-policy'):
            self.assertIn(h, r.headers)
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/app.js').headers['content-type'], 'text/javascript; charset=utf-8')
        self.assertEqual(self.client.get('/../server.py').status_code, 404)
        self.assertEqual(self.client.get('/data/scorecards.json').status_code, 404)

    def test_host_header_allowlist(self):
        r = self.client.get('/api/session', headers={'Host': 'evil.example'})
        self.assertEqual((r.status_code, r.json()), (403, {'error': 'Invalid host'}))

    def test_health_and_readiness(self):
        self.assertEqual(self.client.get('/healthz').json(), {'status': 'ok'})
        r = self.client.get('/readyz')
        self.assertEqual((r.status_code, r.json()['schema']), (200, 'current'))

    def test_private_routes_require_session(self):
        for path in ('/api/summary', '/api/teams', '/api/matches', '/api/players', '/api/players/32722355',
                     '/api/rosters', '/api/notes?team=1', '/api/data'):
            with self.subTest(path):
                r = self.client.get(path)
                self.assertEqual((r.status_code, r.json()), (401, {'error': 'Please sign in'}))
        self.assertEqual(self.client.get('/api/session').json(), {'authenticated': False, 'csrf': None})

    def test_login_session_cookie_and_logout(self):
        r = self.client.post('/api/login', json={'pin': PIN})
        cookie = r.headers['set-cookie']
        for flag in ('HttpOnly', 'SameSite=strict', 'Path=/'):
            self.assertIn(flag.lower(), cookie.lower())
        csrf = r.json()['csrf']
        self.assertEqual(self.client.get('/api/session').json(), {'authenticated': True, 'csrf': csrf})
        self.assertEqual(self.client.get('/api/summary').json()['recorded_runs'], 1923)
        self.assertEqual(self.client.post('/api/logout', json={}).status_code, 403)
        self.assertEqual(self.post('/api/logout', {}, csrf).status_code, 200)
        self.assertEqual(self.client.get('/api/summary').status_code, 401)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM auth_sessions')).scalar_one(), 0)

    def test_wrong_pin_and_throttling(self):
        self.assertEqual(self.client.post('/api/login', json={'pin': '000000'}).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'pin': 'abc'}).json(), {'error': 'Incorrect PIN.'})
        for _ in range(6):
            self.client.post('/api/login', json={'pin': '000000'})
        r = self.client.post('/api/login', json={'pin': PIN})
        self.assertEqual(r.status_code, 429)

    def test_session_expiry_and_pin_reset_revoke_access(self):
        self.login()
        with self.engine.begin() as db:
            db.execute(text('UPDATE auth_sessions SET expires_at = :t'), {'t': datetime.now(timezone.utc) - timedelta(seconds=1)})
        self.assertEqual(self.client.get('/api/summary').status_code, 401)
        self.login()
        with self.engine.begin() as db:
            pin.set_pin(db, '135791')
        self.assertEqual(self.client.get('/api/summary').status_code, 401)

    def test_post_guards(self):
        csrf = self.login()
        r = self.client.post('/api/notes', content='{}', headers={'Content-Type': 'text/plain', 'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 415)
        r = self.client.post('/api/notes', json={'team': 1, 'body': 'x'},
                             headers={'X-CSRF-Token': csrf, 'Origin': 'http://evil.example'})
        self.assertEqual(r.status_code, 403)
        big = json.dumps({'body': 'x' * 2_000_001})
        r = self.client.post('/api/import', content=big, headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 413)
        r = self.client.post('/api/import', content='[1]', headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
        self.assertEqual((r.status_code, r.json()['error']), (400, 'JSON object required'))
        r = self.client.post('/api/import', content='{bad', headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post('/api/notes', {'team': 1, 'body': 'x'}, 'wrong').status_code, 403)

    def test_notes_round_trip_and_validation(self):
        csrf = self.login()
        self.assertEqual(self.post('/api/notes', {'team': 1, 'body': 'Bowl first'}, csrf).json(), {'ok': True})
        n = self.client.get('/api/notes?team=1').json()
        self.assertEqual(n['body'], 'Bowl first')
        self.assertIsNotNone(datetime.fromisoformat(n['updated_at']).tzinfo)
        self.assertEqual(self.post('/api/notes', {'team': 1, 'body': 'x' * 10001}, csrf).status_code, 400)
        self.assertEqual(self.post('/api/notes', {'team': 999, 'body': 'x'}, csrf).status_code, 400)
        self.assertEqual(self.post('/api/notes', {'body': 'x'}, csrf).status_code, 400)
        self.assertEqual(self.client.get('/api/notes').status_code, 400)

    def test_filters_and_lookups(self):
        self.login()
        self.assertEqual(self.client.get('/api/players?team=abc').json(), {'error': 'Invalid filter'})
        self.assertEqual(self.client.get('/api/players?sort=drop').status_code, 400)
        self.assertEqual(self.client.get('/api/players?min=x').status_code, 400)
        self.assertEqual(self.client.get('/api/matches/0').status_code, 404)
        self.assertEqual(self.client.get('/api/players/0').status_code, 404)
        self.assertEqual(self.client.get('/api/nope').json(), {'error': 'Unknown API route'})
        ps = self.client.get('/api/players?sort=average').json()
        averages = [p['average'] for p in ps]
        defined = [a for a in averages if a is not None]
        self.assertEqual(defined, sorted(defined, reverse=True))
        self.assertTrue(all(a is None for a in averages[len(defined):]))
        m = self.client.get('/api/matches/27377965').json()
        self.assertEqual(m['innings'][0]['overs'], '25.0')
        self.assertIsInstance(m['innings'][0]['balls'], int)
        self.assertEqual(self.client.get('/api/rosters?q=pattanaik').json()[0]['name'], 'Pritish Pattanaik')

    def test_import_requires_auth_and_csrf_and_is_atomic(self):
        b = json.loads(BUNDLED_SCORECARDS.read_text())
        self.assertEqual(self.client.post('/api/import', json=b).status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.post('/api/import', json=b).status_code, 403)
        b['matches'][0]['innings'][0]['runs'] += 1
        r = self.post('/api/import', b, csrf)
        self.assertEqual((r.status_code, r.json()['error']), (400, 'Batting runs plus extras do not reconcile'))
        b['matches'][0]['innings'][0]['runs'] -= 1
        self.assertEqual(self.post('/api/import', b, csrf).json(), {'imported': 5})
        self.assertEqual(self.client.get('/api/summary').json()['recorded_runs'], 1923)
        data = self.client.get('/api/data').json()
        self.assertEqual([i['source'] for i in data['imports']], ['User-supplied scorecard JSON', 'Bundled public scorecard snapshot'])

    def test_coach_is_deterministic(self):
        csrf = self.login()
        r = self.post('/api/coach', {'player_id': '27014853', 'question': 'my bowling economy'}, csrf).json()
        self.assertEqual(r['mode'], 'Evidence-based rules; no LLM connected')
        self.assertIn('7 wickets', r['answer'])
        self.assertEqual(self.post('/api/coach', {'question': 'x' * 1001}, csrf).status_code, 400)


if __name__ == '__main__':
    unittest.main()
