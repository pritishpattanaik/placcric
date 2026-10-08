"""Pure validation tests; no database required."""
import copy
import json
import unittest

from app.config import ConfigError, normalise_database_url, redact_url
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
        self.assertEqual(len(validate(bundle())['matches']), 5)

    def test_rejections(self):
        cases = {
            'Batting runs plus extras do not reconcile': lambda b: b['matches'][1]['innings'][0].__setitem__('runs', b['matches'][1]['innings'][0]['runs'] + 1),
            'Source must be a scorecard for this tournament': lambda b: b['matches'][0].__setitem__('source_url', 'https://example.com/scorecard/1'),
            'Invalid teams or winner': lambda b: b['matches'][0].__setitem__('winner', 'Somebody Else'),
            'Two innings required': lambda b: b['matches'][0]['innings'].pop(),
            'Duplicate or invalid match ID': lambda b: b['matches'].append(copy.deepcopy(b['matches'][0])),
            'not_out must be boolean': lambda b: b['matches'][0]['innings'][0]['batting'][0].__setitem__('not_out', 0),
            'Bowling balls do not reconcile': lambda b: b['matches'][0]['innings'][0]['bowling'][0].__setitem__('overs', '3.5'),
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


if __name__ == '__main__':
    unittest.main()
