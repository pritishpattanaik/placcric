"""CricHeroes scorecard PDF reader tests, using synthetic PDFs (invented players). No database needed.

To also check a real downloaded scorecard locally, set PLACCRIC_REAL_SCORECARD_PDF to its path.
Real scorecards contain third-party personal data and must not be committed.
"""
import os
import unittest

from app.ingestion.cricheroes_pdf import ScorecardPdfError, alias_key, clean_name, loose_key, parse
from app.ingestion.records import check_record
from tests import pdf_fixture

T20 = {'overs_per_innings': 20, 'max_overs_per_bowler': 4, 'slug': '', 'name': 'Test League T20 Season 1'}


def parsed(s=None):
    out = parse(pdf_fixture.scorecard_pdf(s))
    out['record']['id'] = '99000001'
    return out


class PdfReaderTests(unittest.TestCase):
    def test_reads_every_field_and_reconciles(self):
        out = parsed()
        r = out['record']
        self.assertEqual((r['team1'], r['team2'], r['winner']), ('Alpha Strikers XI', 'Beta Royals CC', 'Alpha Strikers XI'))
        self.assertEqual((r['date'], r['venue'], r['stage']), ('2026-01-02', 'Test Oval, Testville', 'Final'))
        self.assertEqual(r['toss'], 'Beta Royals CC opt to field')
        self.assertEqual(out['source']['tournament_title'], 'TEST LEAGUE T20 SEASON 1')
        self.assertEqual(r['retrieved_at'], 'PDF generated 1/2/26, 9:00 AM')
        a, b = r['innings']
        self.assertEqual((a['runs'], a['wickets'], a['balls'], a['extras']), (120, 5, 120, 12))
        self.assertEqual(a['extras_detail'], {'wd': 5, 'nb': 1, 'b': 4, 'lb': 2})
        self.assertEqual((len(a['batting']), len(a['bowling']), len(b['batting']), len(b['bowling'])), (6, 5, 10, 5))
        self.assertEqual(a['batting'][1], {'name': 'Ben Two', 'source_name': 'Ben Two (wk) (LHB)', 'runs': 30, 'balls': 25,
                                           'fours': 2, 'sixes': 1, 'dismissal': 'b Jo Ten', 'not_out': False})
        self.assertTrue(a['batting'][-1]['not_out'])
        self.assertEqual(a['bowling'][0], {'name': 'Jo Ten', 'source_name': 'Jo Ten', 'balls': 24, 'runs': 25,
                                           'wickets': 2, 'dots': 10, 'wides': 2, 'no_balls': 0})
        self.assertEqual(check_record(r, T20, require_player_ids=False), ([], []))
        self.assertEqual(out['warnings'], [])
        self.assertEqual(len(out['source']['squads']['Beta Royals CC']), 10)

    def test_names(self):
        self.assertEqual(clean_name('AU Mahi (wk) (RHB)'), 'AU Mahi')
        self.assertEqual(clean_name('Md Hafizur Rahman (Limon) (c)'), 'Md Hafizur Rahman (Limon)')
        self.assertEqual(clean_name('Zakir Hossen ( C )'), 'Zakir Hossen')
        self.assertEqual(alias_key('SHARIF HASAN (Rabbi) (LHB)'), alias_key('Sharif Hasan (rabbi)'))
        self.assertNotEqual(alias_key('Md. Anowar Zahid'), alias_key('Md Anowar Zahid'))
        self.assertEqual(loose_key('Md. Anowar Zahid'), loose_key('Md Anowar Zahid'))

    def test_tie_is_rejected_not_forced_into_a_winner(self):
        out = parsed(pdf_fixture.spec(result='Match tied'))
        self.assertIsNone(out['record']['winner'])
        errors, _ = check_record(out['record'], T20, require_player_ids=False)
        self.assertTrue(any('ties, no-results and super overs' in e for e in errors))

    def test_rain_rule_result_is_flagged(self):
        out = parsed(pdf_fixture.spec(result='Alpha Strikers XI won by 20 runs (DLS)'))
        self.assertTrue(out['record']['dls'])
        self.assertTrue(any('rain rule' in w for w in out['warnings']))

    def test_batter_missing_from_squad_is_warned(self):
        s = pdf_fixture.spec()
        s['squads'][0].remove('Cal Three')
        self.assertEqual(parsed(s)['warnings'],
                         ['Innings 1: batter "Cal Three" is not in the Alpha Strikers XI playing squad listed in the PDF'])

    def test_inconsistent_totals_are_errors(self):
        s = pdf_fixture.spec()
        s['innings'][0]['batting'][0] = ('Ann One (RHB)', 'c Ian Nine b Jo Ten', 41, 30, 4, 1)
        errors, _ = check_record(parsed(s)['record'], T20, require_player_ids=False)
        self.assertIn('Innings 1 (Alpha Strikers XI): batting runs 109 + extras 12 ≠ total 120', errors)
        s = pdf_fixture.spec()
        s['innings'][0]['bowling'][0] = ('Jo Ten', '5', 25, 2, 10, 2, 0)
        errors, _ = check_record(parsed(s)['record'], T20, require_player_ids=False)
        self.assertTrue(any('above the 4-over limit' in e for e in errors))

    def test_unreadable_row_is_an_error_not_skipped(self):
        s = pdf_fixture.spec()
        s['innings'][1]['batting'][3] = ('Lee Twelve (wk) (RHB)', 'b Dev Four', 10, 12, 0, 0)
        pages = pdf_fixture.lines_for(s)
        pages[3] = [l.replace('  10    12', 'ten    12') if 'Lee Twelve' in l else l for l in pages[3]]
        with self.assertRaisesRegex(ScorecardPdfError, 'could not read batting row'):
            parse(pdf_fixture.build_pdf(pages))

    def test_rejects_non_scorecards(self):
        with self.assertRaisesRegex(ScorecardPdfError, 'could not be read as a PDF'):
            parse(b'%PDF-1.4 garbage')
        with self.assertRaisesRegex(ScorecardPdfError, 'does not look like a CricHeroes scorecard'):
            parse(pdf_fixture.build_pdf([['Some other document', 'with no scorecard']]))
        with self.assertRaisesRegex(ScorecardPdfError, 'cricheroes.com'):
            parse(pdf_fixture.build_pdf([['Match Details   Match Result']]))

    @unittest.skipUnless(os.environ.get('PLACCRIC_REAL_SCORECARD_PDF'), 'set PLACCRIC_REAL_SCORECARD_PDF to check a real download')
    def test_real_download(self):
        with open(os.environ['PLACCRIC_REAL_SCORECARD_PDF'], 'rb') as f:
            out = parse(f.read())
        out['record']['id'] = '1'
        errors, _ = check_record(out['record'], {**T20, 'overs_per_innings': 50, 'max_overs_per_bowler': 10},
                                 require_player_ids=False)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
