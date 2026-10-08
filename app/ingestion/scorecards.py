"""Scorecard JSON validation and transactional import (provider: CricHeroes scorecard URLs, tournament 2194193).

Validation is pure and runs before any database write. `import_bundle` must be called with a
connection that is already inside a transaction (for example `with engine.begin() as conn:`),
so a failure part-way through leaves stored statistics unchanged.
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import text

from ..config import ROOT

BUNDLED_SCORECARDS = ROOT / 'data/scorecards.json'
BUNDLED_ROSTERS = ROOT / 'data/rosters.json'
TOURNAMENT_SLUG = 'diwhyn-choice-t25-cricket-carnival-season-2'


def now():
    return datetime.now(timezone.utc)


def overs_to_balls(value):
    s = str(value)
    if not re.fullmatch(r'\d+(?:\.[0-5])?', s):
        raise ValueError('Overs must be cricket notation, for example 22.3')
    p = s.split('.')
    return int(p[0]) * 6 + (int(p[1]) if len(p) > 1 else 0)


def overs(balls):
    return f'{balls // 6}.{balls % 6}'


def integer(v, field, maximum=100000):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= maximum:
        raise ValueError(f'Invalid {field}')
    return v


def text_field(v, field, limit=500):
    if not isinstance(v, str) or not v.strip() or len(v) > limit:
        raise ValueError(f'Invalid {field}')
    return v.strip()


def content_hash(bundle):
    canonical = json.dumps(bundle, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def validate(bundle):
    if not isinstance(bundle, dict) or not isinstance(bundle.get('matches'), list) or not 1 <= len(bundle['matches']) <= 100:
        raise ValueError('Expected 1–100 scorecards')
    seen = set()
    for m in bundle['matches']:
        if not isinstance(m, dict):
            raise ValueError('Each scorecard must be an object')
        mid = text_field(m.get('id'), 'match ID', 20)
        if not mid.isdigit() or mid in seen:
            raise ValueError('Duplicate or invalid match ID')
        seen.add(mid)
        url = urlparse(text_field(m.get('source_url'), 'source URL', 1000))
        if url.scheme != 'https' or url.hostname != 'cricheroes.com' or not url.path.startswith(f'/scorecard/{mid}/{TOURNAMENT_SLUG}/'):
            raise ValueError('Source must be a scorecard for this tournament')
        datetime.strptime(m['date'], '%Y-%m-%d')
        for k in ['venue', 'team1', 'team2', 'result', 'winner']:
            text_field(m.get(k), k)
        if m['team1'] == m['team2'] or m['winner'] not in [m['team1'], m['team2']]:
            raise ValueError('Invalid teams or winner')
        if not isinstance(m.get('innings'), list) or len(m['innings']) != 2:
            raise ValueError('Two innings required')
        for no, inn in enumerate(m['innings']):
            if inn['team'] != m['team' + str(no + 1)]:
                raise ValueError('Innings team mismatch')
            for k in ['runs', 'wickets', 'extras']:
                integer(inn.get(k), k)
            if inn['wickets'] > 10:
                raise ValueError('Invalid wickets')
            balls = overs_to_balls(inn['overs'])
            if balls > 150:
                raise ValueError('T25 innings exceeds 150 balls')
            if not isinstance(inn.get('batting'), list) or not isinstance(inn.get('bowling'), list):
                raise ValueError('Batting and bowling lists required')
            if not 1 <= len(inn['batting']) <= 20 or not 1 <= len(inn['bowling']) <= 15:
                raise ValueError('Invalid innings size')
            for rows, kind in [(inn['batting'], 'batting'), (inn['bowling'], 'bowling')]:
                ids = set()
                for r in rows:
                    pid = text_field(r.get('player_id'), 'player ID', 20)
                    if not pid.isdigit() or pid in ids:
                        raise ValueError('Duplicate or invalid player ID')
                    ids.add(pid)
                    text_field(r.get('name'), 'player name', 150)
                    for k in (['runs', 'balls', 'fours', 'sixes'] if kind == 'batting' else ['runs', 'wickets', 'dots', 'wides', 'no_balls']):
                        integer(r.get(k), k)
                    if kind == 'batting':
                        if not isinstance(r.get('not_out'), bool):
                            raise ValueError('not_out must be boolean')
                        if r['fours'] * 4 + r['sixes'] * 6 > r['runs']:
                            raise ValueError('Boundary runs exceed batting runs')
                        if len(r.get('dismissal', '')) > 500:
                            raise ValueError('Dismissal too long')
                    else:
                        rb = overs_to_balls(r['overs'])
                        if rb > 30 or r['dots'] > rb or r['wickets'] > 10:
                            raise ValueError('Invalid bowling spell')
            if sum(r['runs'] for r in inn['batting']) + inn['extras'] != inn['runs']:
                raise ValueError('Batting runs plus extras do not reconcile')
            if sum(overs_to_balls(r['overs']) for r in inn['bowling']) != balls:
                raise ValueError('Bowling balls do not reconcile')
            if sum(r['wickets'] for r in inn['bowling']) > inn['wickets']:
                raise ValueError('Bowling wickets exceed innings wickets')
    return bundle


def team_id(db, name):
    db.execute(text('INSERT INTO teams(name) VALUES (:n) ON CONFLICT (name) DO NOTHING'), {'n': name})
    return db.execute(text('SELECT id FROM teams WHERE name = :n'), {'n': name}).scalar_one()


def import_bundle(db, bundle, source='local JSON'):
    """Validate, then upsert every match in the bundle. Re-importing a match ID replaces its scores."""
    validate(bundle)
    retrieved_at = str(bundle.get('retrieved_at') or now().isoformat(timespec='seconds'))
    for m in bundle['matches']:
        a, b, w = team_id(db, m['team1']), team_id(db, m['team2']), team_id(db, m['winner'])
        db.execute(text(
            'INSERT INTO matches(id,date,venue,team1,team2,winner,result,toss,pom,dls,warning,source_url,retrieved_at) '
            'VALUES (:id,:date,:venue,:t1,:t2,:w,:result,:toss,:pom,:dls,:warning,:url,:retrieved) '
            'ON CONFLICT (id) DO UPDATE SET date=excluded.date,venue=excluded.venue,team1=excluded.team1,'
            'team2=excluded.team2,winner=excluded.winner,result=excluded.result,toss=excluded.toss,pom=excluded.pom,'
            'dls=excluded.dls,warning=excluded.warning,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at'),
            dict(id=m['id'], date=date.fromisoformat(m['date']), venue=m['venue'], t1=a, t2=b, w=w, result=m['result'],
                 toss=m.get('toss', ''), pom=m.get('pom', ''), dls=bool(m.get('dls', False)), warning=m.get('warning', ''),
                 url=m['source_url'], retrieved=retrieved_at))
        db.execute(text('DELETE FROM innings WHERE match_id = :id'), {'id': m['id']})
        for num, inn in enumerate(m['innings'], 1):
            db.execute(text('INSERT INTO innings VALUES (:m,:n,:t,:runs,:wk,:balls,:extras)'),
                       dict(m=m['id'], n=num, t=team_id(db, inn['team']), runs=inn['runs'], wk=inn['wickets'],
                            balls=overs_to_balls(inn['overs']), extras=inn['extras']))
            for kind in ['batting', 'bowling']:
                for pos, r in enumerate(inn[kind], 1):
                    db.execute(text('INSERT INTO players(id,name) VALUES (:id,:name) '
                                    'ON CONFLICT (id) DO UPDATE SET name=excluded.name'),
                               {'id': r['player_id'], 'name': r['name']})
                    row = dict(m=m['id'], n=num, p=r['player_id'], pos=pos, runs=r['runs'])
                    if kind == 'batting':
                        db.execute(text('INSERT INTO batting VALUES (:m,:n,:p,:pos,:runs,:balls,:fours,:sixes,:dis,:no)'),
                                   dict(row, balls=r['balls'], fours=r['fours'], sixes=r['sixes'],
                                        dis=r.get('dismissal', ''), no=r['not_out']))
                    else:
                        db.execute(text('INSERT INTO bowling VALUES (:m,:n,:p,:pos,:balls,:runs,:wk,:dots,:wd,:nb)'),
                                   dict(row, balls=overs_to_balls(r['overs']), wk=r['wickets'], dots=r['dots'],
                                        wd=r['wides'], nb=r['no_balls']))
    db.execute(text('INSERT INTO import_log(imported_at,matches,source,content_sha256) VALUES (:at,:n,:src,:h)'),
               {'at': now(), 'n': len(bundle['matches']), 'src': source, 'h': content_hash(bundle)})
    return len(bundle['matches'])


def seed(db):
    """Idempotently load bundled club listings and the bundled scorecard snapshot.

    Never overwrites an existing match (so later corrections survive a re-run) and never deletes data.
    Returns a dict of what was added.
    """
    roster = json.loads(BUNDLED_ROSTERS.read_text(encoding='utf-8'))
    bundle = validate(json.loads(BUNDLED_SCORECARDS.read_text(encoding='utf-8')))
    added_listings = 0
    for t in roster['teams']:
        tid = team_id(db, t['name'])
        for p in t['players']:
            added_listings += db.execute(text('INSERT INTO roster_entries VALUES (:t,:n,:s) ON CONFLICT DO NOTHING'),
                                         {'t': tid, 'n': p['name'], 's': roster['source']}).rowcount
    existing = set(db.execute(text('SELECT id FROM matches')).scalars())
    missing = [m for m in bundle['matches'] if m['id'] not in existing]
    if missing:
        import_bundle(db, dict(bundle, matches=missing), 'Bundled public scorecard snapshot')
    return {'club_listings_added': added_listings, 'matches_added': len(missing),
            'matches_already_present': len(bundle['matches']) - len(missing)}
