import copy,json,tempfile,unittest
from pathlib import Path
from app.database import ROOT,initialize,connect,import_bundle,overs_to_balls
from app.analytics import players,profile,summary
from app.security import set_pin,login,session

class AppTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3';initialize(self.path);self.db=connect(self.path)
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_scorecards_reconcile(self):
  s=summary(self.db);self.assertEqual(s['completed'],5);self.assertEqual(s['recorded_runs'],1923);self.assertEqual(len(s['teams']),15)
  self.assertEqual(overs_to_balls('22.3'),135)
  with self.assertRaises(ValueError):overs_to_balls('22.6')
 def test_identity_and_metrics(self):
  p=profile(self.db,'32722355');self.assertEqual((p['runs'],p['balls'],p['innings']),(0,4,1));self.assertEqual(p['average'],0)
  p=profile(self.db,'1936055');self.assertEqual(p['runs'],180);self.assertEqual(p['strike_rate'],225);self.assertIsNone(p['average'])
  p=profile(self.db,'27014853');self.assertEqual(p['wickets'],7);self.assertEqual(p['economy'],3)
 def test_pin_session_and_lockout(self):
  set_pin(self.db,'123456');s,e=login(self.db,'123456','local');self.assertIsNone(e);self.assertIsNotNone(session(self.db,s['token']))
  self.assertIsNone(session(self.db,'guessed'))
  for _ in range(8):self.assertIsNone(login(self.db,'000000','other')[0])
  self.assertIn('Too many',login(self.db,'123456','other')[1])
  set_pin(self.db,'654321');self.assertIsNone(session(self.db,s['token']))
 def test_failed_import_keeps_old_scores(self):
  b=json.loads(ROOT.joinpath('data/scorecards.json').read_text());b['matches'][1]['innings'][0]['runs']+=1
  with self.assertRaises(ValueError):import_bundle(self.db,b)
  self.assertEqual(summary(self.db)['recorded_runs'],1923)
 def test_repeat_import_is_idempotent(self):
  b=json.loads(ROOT.joinpath('data/scorecards.json').read_text());import_bundle(self.db,b);initialize(self.path)
  self.assertEqual(summary(self.db)['completed'],5);self.assertEqual(profile(self.db,'27014853')['wickets'],7)
 def test_team_scope(self):
  tid=self.db.execute("SELECT id FROM teams WHERE name='UTKAL Cricket Club (UCC).'").fetchone()[0]
  s=summary(self.db,tid);self.assertEqual(s['recorded_runs'],188);self.assertEqual(s['completed'],1)
  self.assertTrue(all(tid in p['team_ids'] for p in players(self.db,tid)))
if __name__=='__main__':unittest.main()
