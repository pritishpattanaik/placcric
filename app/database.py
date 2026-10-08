import json,sqlite3,re
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect(path):
 db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=15000');return db

def overs_to_balls(value):
 s=str(value)
 if not re.fullmatch(r'\d+(?:\.[0-5])?',s): raise ValueError('Overs must be cricket notation, for example 22.3')
 p=s.split('.');return int(p[0])*6+(int(p[1]) if len(p)>1 else 0)
def overs(balls): return f'{balls//6}.{balls%6}'
def integer(v,field,maximum=100000):
 if isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=maximum: raise ValueError(f'Invalid {field}')
 return v
def text(v,field,limit=500):
 if not isinstance(v,str) or not v.strip() or len(v)>limit:raise ValueError(f'Invalid {field}')
 return v.strip()
def validate(bundle):
 from urllib.parse import urlparse
 if not isinstance(bundle,dict) or not isinstance(bundle.get('matches'),list) or not 1<=len(bundle['matches'])<=100:raise ValueError('Expected 1–100 scorecards')
 seen=set()
 for m in bundle['matches']:
  mid=text(m.get('id'),'match ID',20)
  if not mid.isdigit() or mid in seen:raise ValueError('Duplicate or invalid match ID')
  seen.add(mid)
  url=urlparse(text(m.get('source_url'),'source URL',1000))
  if url.scheme!='https' or url.hostname!='cricheroes.com' or not url.path.startswith('/scorecard/'+mid+'/diwhyn-choice-t25-cricket-carnival-season-2/'):raise ValueError('Source must be a scorecard for this tournament')
  datetime.strptime(m['date'],'%Y-%m-%d')
  for k in ['venue','team1','team2','result','winner']:text(m.get(k),k)
  if m['team1']==m['team2'] or m['winner'] not in [m['team1'],m['team2']]:raise ValueError('Invalid teams or winner')
  if len(m.get('innings',[]))!=2:raise ValueError('Two innings required')
  for no,inn in enumerate(m['innings']):
   if inn['team']!=m['team'+str(no+1)]:raise ValueError('Innings team mismatch')
   for k in ['runs','wickets','extras']:integer(inn.get(k),k)
   if inn['wickets']>10:raise ValueError('Invalid wickets')
   balls=overs_to_balls(inn['overs'])
   if balls>150:raise ValueError('T25 innings exceeds 150 balls')
   if not isinstance(inn.get('batting'),list) or not isinstance(inn.get('bowling'),list):raise ValueError('Batting and bowling lists required')
   if not 1<=len(inn['batting'])<=20 or not 1<=len(inn['bowling'])<=15:raise ValueError('Invalid innings size')
   for rows,kind in [(inn['batting'],'batting'),(inn['bowling'],'bowling')]:
    ids=set()
    for r in rows:
     pid=text(r.get('player_id'),'player ID',20)
     if not pid.isdigit() or pid in ids:raise ValueError('Duplicate or invalid player ID')
     ids.add(pid);text(r.get('name'),'player name',150)
     for k in (['runs','balls','fours','sixes'] if kind=='batting' else ['runs','wickets','dots','wides','no_balls']):integer(r.get(k),k)
     if kind=='batting':
      if not isinstance(r.get('not_out'),bool):raise ValueError('not_out must be boolean')
      if r['fours']*4+r['sixes']*6>r['runs']:raise ValueError('Boundary runs exceed batting runs')
      if len(r.get('dismissal',''))>500:raise ValueError('Dismissal too long')
     else:
      rb=overs_to_balls(r['overs'])
      if rb>30 or r['dots']>rb or r['wickets']>10:raise ValueError('Invalid bowling spell')
   if sum(r['runs'] for r in inn['batting'])+inn['extras']!=inn['runs']:raise ValueError('Batting runs plus extras do not reconcile')
   if sum(overs_to_balls(r['overs']) for r in inn['bowling'])!=balls:raise ValueError('Bowling balls do not reconcile')
   if sum(r['wickets'] for r in inn['bowling'])>inn['wickets']:raise ValueError('Bowling wickets exceed innings wickets')
 return bundle

def import_bundle(db,bundle,source='local JSON'):
 validate(bundle)
 def tid(name):
  db.execute('INSERT OR IGNORE INTO teams(name) VALUES(?)',(name,));return db.execute('SELECT id FROM teams WHERE name=?',(name,)).fetchone()[0]
 with db:
  for m in bundle['matches']:
   a,b,w=tid(m['team1']),tid(m['team2']),tid(m['winner'])
   db.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET date=excluded.date,venue=excluded.venue,team1=excluded.team1,team2=excluded.team2,winner=excluded.winner,result=excluded.result,toss=excluded.toss,pom=excluded.pom,dls=excluded.dls,warning=excluded.warning,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at',(m['id'],m['date'],m['venue'],a,b,w,m['result'],m.get('toss',''),m.get('pom',''),int(m.get('dls',False)),m.get('warning',''),m['source_url'],bundle.get('retrieved_at',now())))
   db.execute('DELETE FROM innings WHERE match_id=?',(m['id'],))
   for num,inn in enumerate(m['innings'],1):
    db.execute('INSERT INTO innings VALUES(?,?,?,?,?,?,?)',(m['id'],num,tid(inn['team']),inn['runs'],inn['wickets'],overs_to_balls(inn['overs']),inn['extras']))
    for kind in ['batting','bowling']:
     for pos,r in enumerate(inn[kind],1):
      db.execute('INSERT INTO players VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',(r['player_id'],r['name']))
      if kind=='batting':db.execute('INSERT INTO batting VALUES(?,?,?,?,?,?,?,?,?,?)',(m['id'],num,r['player_id'],pos,r['runs'],r['balls'],r['fours'],r['sixes'],r.get('dismissal',''),int(r['not_out'])))
      else:db.execute('INSERT INTO bowling VALUES(?,?,?,?,?,?,?,?,?,?)',(m['id'],num,r['player_id'],pos,overs_to_balls(r['overs']),r['runs'],r['wickets'],r['dots'],r['wides'],r['no_balls']))
  db.execute('INSERT INTO import_log(imported_at,matches,source) VALUES(?,?,?)',(now(),len(bundle['matches']),source))
 return len(bundle['matches'])

def initialize(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with connect(path) as db:
  db.execute('PRAGMA journal_mode=WAL');db.executescript(ROOT.joinpath('app/schema.sql').read_text())
  if not db.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
   roster=json.loads(ROOT.joinpath('data/rosters.json').read_text())
   with db:
    for t in roster['teams']:
     db.execute('INSERT OR IGNORE INTO teams(name) VALUES(?)',(t['name'],));i=db.execute('SELECT id FROM teams WHERE name=?',(t['name'],)).fetchone()[0]
     for p in t['players']:db.execute('INSERT OR IGNORE INTO roster_entries VALUES(?,?,?)',(i,p['name'],roster['source']))
   import_bundle(db,json.loads(ROOT.joinpath('data/scorecards.json').read_text()),'Bundled verified public scorecards')
   db.execute("INSERT INTO meta VALUES('seeded','1')");db.commit()
  db.execute('PRAGMA optimize')
