#!/usr/bin/env python3
"""PlacCric local application. Python 3.10+, standard library only."""
import argparse,getpass,json,os,sqlite3,sys
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from app.database import ROOT,connect,initialize,import_bundle,now
from app import analytics,security

class Handler(BaseHTTPRequestHandler):
 server_version='PlacCric/2.0'
 def log_message(self,*args):pass
 def headers_common(self):
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
 def send(self,status,obj,cookie=None):
  body=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.headers_common();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers();self.wfile.write(body)
 def allowed_host(self):
  return self.headers.get('Host','') in [f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}']
 def get_session(self,db):
  try:c=SimpleCookie(self.headers.get('Cookie',''));token=c['placcric_session'].value if 'placcric_session' in c else ''
  except Exception:token=''
  return security.session(db,token)
 def do_GET(self):
  if not self.allowed_host():return self.send(403,{'error':'Invalid host'})
  path=urlparse(self.path).path;q=parse_qs(urlparse(self.path).query)
  if path.startswith('/api/'):
   with connect(self.server.db_path) as db:
    s=self.get_session(db)
    if path=='/api/session':return self.send(200,{'authenticated':bool(s),'csrf':s['csrf'] if s else None})
    if not s:return self.send(401,{'error':'Please sign in'})
    try:
     team=int(q['team'][0]) if q.get('team') and q['team'][0] else None
     if path=='/api/summary':return self.send(200,analytics.summary(db,team))
     if path=='/api/teams':return self.send(200,analytics.teams(db))
     if path=='/api/matches':return self.send(200,analytics.match_list(db,team))
     if path.startswith('/api/matches/'):
      m=analytics.match_detail(db,path.rsplit('/',1)[1]);return self.send(200 if m else 404,m or {'error':'Match not found'})
     if path=='/api/players':
      ps=analytics.players(db,team);query=q.get('q',[''])[0].lower();minimum=int(q.get('min',['0'])[0]);sort=q.get('sort',['runs'])[0]
      ps=[p for p in ps if query in p['name'].lower() and p['innings']>=minimum]
      if sort not in ['runs','wickets','strike_rate','average','economy','name']:raise ValueError('Invalid sort')
      ps.sort(key=lambda p: ((p[sort] is None,p[sort] if sort in ['name','economy'] else -(p[sort] or 0)),p['name']))
      return self.send(200,ps)
     if path.startswith('/api/players/'):
      p=analytics.profile(db,path.rsplit('/',1)[1],team);return self.send(200 if p else 404,p or {'error':'Player not found'})
     if path=='/api/rosters':
      sql='SELECT r.*,t.name team_name FROM roster_entries r JOIN teams t ON t.id=r.team_id WHERE lower(r.name) LIKE ?';args=['%'+q.get('q',[''])[0].lower()+'%']
      if team:sql+=' AND team_id=?';args.append(team)
      return self.send(200,analytics.records(db,sql+' ORDER BY t.name,r.name',args))
     if path=='/api/notes':
      if not team:raise ValueError('Team required')
      n=db.execute('SELECT body,updated_at FROM notes WHERE team_id=?',(team,)).fetchone();return self.send(200,dict(n) if n else {'body':'','updated_at':None})
     if path=='/api/data':
      return self.send(200,{'imports':analytics.records(db,'SELECT * FROM import_log ORDER BY id DESC LIMIT 20'),'warnings':analytics.records(db,"SELECT id,warning,source_url FROM matches WHERE warning!=''"),'coverage':analytics.summary(db)['coverage']})
     return self.send(404,{'error':'Unknown API route'})
    except (ValueError,KeyError,TypeError):return self.send(400,{'error':'Invalid filter'})
  files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css','/favicon.svg':'favicon.svg'}
  if path not in files:return self.send(404,{'error':'Not found'})
  body=ROOT.joinpath('web',files[path]).read_bytes();self.send_response(200);self.headers_common();self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'}[files[path].rsplit('.',1)[1]]);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_POST(self):
  if not self.allowed_host():return self.send(403,{'error':'Invalid host'})
  expected='http://'+self.headers['Host'];origin=self.headers.get('Origin')
  if origin and origin!=expected:return self.send(403,{'error':'Invalid origin'})
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'JSON required'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=2_000_000:return self.send(413,{'error':'Upload must be at most 2 MB'})
   data=json.loads(self.rfile.read(size));path=urlparse(self.path).path
   if not isinstance(data,dict):raise ValueError('JSON object required')
   with connect(self.server.db_path) as db:
    if path=='/api/login':
     s,error=security.login(db,data.get('pin'),self.client_address[0])
     if error:return self.send(429 if error.startswith('Too many') else 401,{'error':error})
     return self.send(200,{'csrf':s['csrf']},f"placcric_session={s['token']}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
    s=self.get_session(db)
    if not s:return self.send(401,{'error':'Please sign in'})
    if not security.hmac.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']):return self.send(403,{'error':'Invalid session verification'})
    if path=='/api/logout':
     with db:db.execute('DELETE FROM sessions WHERE token_hash=?',(s['token_hash'],))
     return self.send(200,{'ok':True},'placcric_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
    if path=='/api/notes':
     team=int(data['team']);body=data['body']
     if not isinstance(body,str) or len(body)>10000:raise ValueError('Notes must be at most 10000 characters')
     with db:db.execute('INSERT INTO notes VALUES(?,?,?) ON CONFLICT(team_id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',(team,body,now()))
     return self.send(200,{'ok':True})
    if path=='/api/coach':
     question=data.get('question','')
     if not isinstance(question,str) or len(question)>1000:raise ValueError('Question must be at most 1000 characters')
     return self.send(200,{'answer':analytics.coach(db,str(data.get('player_id','')),question),'mode':'Evidence-based rules; no LLM connected'})
    if path=='/api/import':return self.send(200,{'imported':import_bundle(db,data,'User-supplied scorecard JSON')})
    return self.send(404,{'error':'Unknown API route'})
  except (ValueError,KeyError,TypeError,sqlite3.IntegrityError) as e:return self.send(400,{'error':str(e)[:200]})

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--db',default=str(ROOT/'data/placcric.sqlite3'));parser.add_argument('--reset-pin',action='store_true');args=parser.parse_args()
 initialize(args.db)
 with connect(args.db) as db:
  if args.reset_pin or not db.execute('SELECT 1 FROM auth').fetchone():
   pin=os.environ.get('PLACCRIC_PIN')
   if not pin:
    pin=getpass.getpass('Create your PlacCric PIN (6–12 digits): ')
    if pin!=getpass.getpass('Confirm PIN: '):sys.exit('PINs did not match; run again.')
   try:security.set_pin(db,pin)
   except ValueError as e:sys.exit(str(e))
 if args.reset_pin:print('PIN updated. Existing sessions ended.');return
 try:
  server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.db_path=args.db
 except OSError:sys.exit(f'Port {args.port} is already in use. Stop the old http.server with Ctrl+C, then run again.')
 print(f'PlacCric running at http://localhost:{args.port} (Ctrl+C to stop)',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:print('\nPlacCric stopped.')
 finally:server.server_close()
if __name__=='__main__':main()
