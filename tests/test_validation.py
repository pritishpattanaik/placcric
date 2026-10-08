"""Pure validation tests; no database required."""
import copy
import json
import os
import unittest
from unittest import mock

from app.config import ConfigError, get_settings, normalise_database_url, redact_url
from app.ingestion.scorecards import BUNDLED_SCORECARDS, content_hash, overs, overs_to_balls, validate


def bundle():
    return json.loads(BUNDLED_SCORECARDS.read_text())


class ValidationTests(unittest.TestCase):
    def test_overs_are_cricket_notation_stored_as_legal_balls(self):
        self.assertEqual(overs_to_balls('22.3'), 135)
        self.assertEqual(overs_to_balls('25.0'), 150)
        self.assertEqual(overs(135), '22.3')
        for bad in ('22.6', '1.25', '-1', 'abc', ''):
            with self.assertRaises(ValueError):
                overs_to_balls(bad)

    def test_bundled_snapshot_validates(self):
        self.assertEqual(len(validate(bundle())), 5)

    def test_rejections(self):
        cases = {
            r'batting runs \d+ \+ extras \d+ ≠ total': lambda b: b['matches'][1]['innings'][0].__setitem__('runs', b['matches'][1]['innings'][0]['runs'] + 1),
            'Source URL must be this match': lambda b: b['matches'][0].__setitem__('source_url', 'https://example.com/scorecard/1'),
            'Only completed matches with a winner': lambda b: b['matches'][0].__setitem__('winner', 'Somebody Else'),
            'Exactly two innings are required': lambda b: b['matches'][0]['innings'].pop(),
            'Duplicate or invalid match ID': lambda b: b['matches'].append(copy.deepcopy(b['matches'][0])),
            'not-out flag must be true or false': lambda b: b['matches'][0]['innings'][0]['batting'][0].__setitem__('not_out', 0),
            'bowlers delivered 24.5 overs': lambda b: b['matches'][0]['innings'][0]['bowling'][0].__setitem__('overs', '3.5'),
        }
        for message, mutate in cases.items():
            with self.subTest(message):
                b = bundle()
                mutate(b)
                with self.assertRaisesRegex(ValueError, message):
                    validate(b)
        with self.assertRaises(ValueError):
            validate({'matches': []})

    def test_content_hash_is_order_independent_for_keys(self):
        b = bundle()
        reordered = json.loads(json.dumps(b, sort_keys=True))
        self.assertEqual(content_hash(b), content_hash(reordered))
        b['matches'][0]['venue'] += ' '
        self.assertNotEqual(content_hash(b), content_hash(reordered))


class ConfigTests(unittest.TestCase):
    def test_only_postgresql_urls_are_accepted(self):
        self.assertEqual(normalise_database_url('postgresql://u:p@h/db'), 'postgresql+psycopg://u:p@h/db')
        self.assertEqual(normalise_database_url('postgres://u@h/db'), 'postgresql+psycopg://u@h/db')
        for bad in ('', None, 'sqlite:///data/placcric.sqlite3', 'mysql://u@h/db'):
            with self.assertRaises(ConfigError):
                normalise_database_url(bad)

    def test_passwords_are_redacted(self):
        self.assertEqual(redact_url('postgresql+psycopg://u:s3cret@h:5432/db'), 'postgresql+psycopg://u:***@h:5432/db')
        self.assertNotIn('s3cret', redact_url('postgresql://u:s3cret@h/db'))

    def settings(self, **env):
        base = {'DATABASE_URL': 'postgresql://u@h/db'}
        with mock.patch.dict(os.environ, dict(base, **env), clear=True), mock.patch('app.config.load_env_file'):
            return get_settings()

    def test_development_defaults_are_local_only(self):
        s = self.settings()
        self.assertEqual((s.host, s.port, s.environment), ('127.0.0.1', 8000, 'development'))
        self.assertEqual(s.allowed_hosts, ('localhost:8000', '127.0.0.1:8000'))
        self.assertFalse(s.cookie_secure)
        self.assertEqual(s.forwarded_allow_ips, '')
        self.assertEqual(self.settings(PLACCRIC_PORT='9000').allowed_hosts, ('localhost:9000', '127.0.0.1:9000'))

    def test_production_settings_from_environment(self):
        s = self.settings(PLACCRIC_ENV='production', PLACCRIC_HOST='0.0.0.0',
                          PLACCRIC_ALLOWED_HOSTS=' placcric.example.com , localhost:8000 ',
                          PLACCRIC_FORWARDED_ALLOW_IPS='*')
        self.assertTrue(s.cookie_secure)
        self.assertEqual(s.allowed_hosts, ('placcric.example.com', 'localhost:8000'))
        self.assertEqual((s.host, s.forwarded_allow_ips), ('0.0.0.0', '*'))
        self.assertFalse(self.settings(PLACCRIC_ENV='production', PLACCRIC_COOKIE_SECURE='false').cookie_secure)
        for bad in ({'PLACCRIC_ENV': 'prod'}, {'PLACCRIC_COOKIE_SECURE': 'maybe'}, {'PLACCRIC_PORT': 'x'}):
            with self.subTest(bad), self.assertRaises(ConfigError):
                self.settings(**bad)


if __name__ == '__main__':
    unittest.main()
