"""Provider-neutral match records.

A *record* is one completed match in a single canonical shape, whatever its source (JSON bundle
or scorecard PDF). Overs are already integer legal balls:

    {id, date, venue, team1, team2, winner, result, toss, pom, dls, warning, stage, source_url,
     retrieved_at, innings: [{team, runs, wickets, balls, extras, extras_detail?,
       batting: [{player_id?, name, runs, balls, fours, sixes, dismissal, not_out}],
       bowling: [{player_id?, name, balls, runs, wickets, dots, wides, no_balls}]}]}

`check_record` validates a record against its tournament's playing conditions and returns every
problem at once (errors block publishing; warnings are shown for review). `publish` writes a
record to the scorecard tables and stores it as a new revision, inside the caller's transaction.
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import text

MATCH_FIELDS = ('date', 'venue', 'team1', 'team2', 'winner', 'result', 'toss', 'pom', 'dls', 'warning', 'stage',
                'source_url')
INNINGS_FIELDS = ('team', 'runs', 'wickets', 'balls', 'extras')
BATTING_FIELDS = ('runs', 'balls', 'fours', 'sixes', 'dismissal', 'not_out')
BOWLING_FIELDS = ('balls', 'runs', 'wickets', 'dots', 'wides', 'no_balls')
MAX_INT = 100000


def now():
    return datetime.now(timezone.utc)


def overs(balls):
    return f'{balls // 6}.{balls % 6}'


def rules_for(tournament):
    """Playing conditions from a tournaments row (mapping)."""
    return {'overs_per_innings': tournament['overs_per_innings'],
            'max_overs_per_bowler': tournament['max_overs_per_bowler'],
            'slug': tournament.get('slug') or '', 'name': tournament['name']}


def score_view(record):
    """The parts of a record that define the scorecard. Names and retrieval time are excluded, so a
    re-downloaded file with the same scores, or a corrected spelling, is not a scoring change."""
    return {'id': record['id'], **{k: record.get(k) for k in MATCH_FIELDS if k != 'source_url'},
            'innings': [{**{k: inn[k] for k in INNINGS_FIELDS},
                         'batting': [{'player_id': r.get('player_id'), **{k: r[k] for k in BATTING_FIELDS}}
                                     for r in inn['batting']],
                         'bowling': [{'player_id': r.get('player_id'), **{k: r[k] for k in BOWLING_FIELDS}}
                                     for r in inn['bowling']]}
                        for inn in record['innings']]}


def record_hash(record):
    canonical = json.dumps(score_view(record), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _is_int(v, maximum=MAX_INT):
    return not isinstance(v, bool) and isinstance(v, int) and 0 <= v <= maximum


def check_record(record, rules, require_player_ids=True):
    """Return (errors, warnings) as lists of human-readable strings. Never raises for bad data."""
    errors, warnings = [], []
    mid = str(record.get('id') or '')
    if not re.fullmatch(r'\d{1,20}', mid):
        errors.append('Match ID must be the numeric CricHeroes match ID')
    try:
        date.fromisoformat(str(record.get('date')))
    except ValueError:
        errors.append('Match date is missing or not YYYY-MM-DD')
    for k in ('venue', 'team1', 'team2', 'result'):
        v = record.get(k)
        if not isinstance(v, str) or not v.strip() or len(v) > 500:
            errors.append(f'Missing or invalid {k}')
    url = record.get('source_url') or ''
    if url:
        expected = f'https://cricheroes.com/scorecard/{mid}/' + (rules['slug'] + '/' if rules.get('slug') else '')
        if not url.startswith(expected):
            errors.append(f'Source URL must be this match\'s CricHeroes scorecard ({expected}…)')
    t1, t2 = record.get('team1'), record.get('team2')
    if t1 == t2:
        errors.append('The two teams must be different')
    if record.get('winner') not in (t1, t2):
        errors.append('Only completed matches with a winner are supported; ties, no-results and super overs '
                      'are not imported yet')
    innings = record.get('innings') or []
    if len(innings) != 2:
        errors.append(f'Exactly two innings are required (found {len(innings)})')
        return errors, warnings
    max_balls = rules['overs_per_innings'] * 6
    max_spell = rules['max_overs_per_bowler'] * 6
    for no, inn in enumerate(innings, 1):
        where = f'Innings {no} ({inn.get("team", "?")})'
        if inn.get('team') != (t1 if no == 1 else t2):
            errors.append(f'{where}: batting order does not match team1/team2')
        if not all(_is_int(inn.get(k)) for k in ('runs', 'wickets', 'balls', 'extras')):
            errors.append(f'{where}: runs, wickets, balls and extras must be whole numbers')
            continue
        if inn['wickets'] > 10:
            errors.append(f'{where}: more than 10 wickets')
        if inn['balls'] > max_balls:
            errors.append(f'{where}: {overs(inn["balls"])} overs exceeds the {rules["overs_per_innings"]}-over limit')
        bat, bowl = inn.get('batting') or [], inn.get('bowling') or []
        if not 1 <= len(bat) <= 20 or not 1 <= len(bowl) <= 15:
            errors.append(f'{where}: expected 1–20 batters and 1–15 bowlers')
            continue
        for kind, rows, fields in (('batting', bat, BATTING_FIELDS), ('bowling', bowl, BOWLING_FIELDS)):
            seen = set()
            for r in rows:
                name = r.get('name') or '?'
                if not isinstance(r.get('name'), str) or not r['name'].strip() or len(r['name']) > 150:
                    errors.append(f'{where} {kind}: invalid player name')
                ident = r.get('player_id') if require_player_ids else (r.get('player_id') or name.casefold())
                if require_player_ids and not (isinstance(ident, str) and 0 < len(ident) <= 32):
                    errors.append(f'{where} {kind}: {name} has no player ID')
                elif ident in seen:
                    errors.append(f'{where} {kind}: {name} appears more than once')
                seen.add(ident)
                numeric = [f for f in fields if f not in ('dismissal', 'not_out')]
                if not all(_is_int(r.get(f)) for f in numeric):
                    errors.append(f'{where} {kind}: {name} has a missing or negative figure')
                    continue
                if kind == 'batting':
                    if not isinstance(r.get('not_out'), bool):
                        errors.append(f'{where}: {name} not-out flag must be true or false')
                    if r['fours'] * 4 + r['sixes'] * 6 > r['runs']:
                        errors.append(f'{where}: {name} boundary runs exceed runs scored')
                else:
                    if r['balls'] > max_spell:
                        errors.append(f'{where}: {name} bowled {overs(r["balls"])} overs, above the '
                                      f'{rules["max_overs_per_bowler"]}-over limit')
                    if r['dots'] > r['balls'] or r['wickets'] > 10:
                        errors.append(f'{where}: {name} has an impossible bowling spell')
        if errors:
            continue
        bat_runs = sum(r['runs'] for r in bat)
        if bat_runs + inn['extras'] != inn['runs']:
            errors.append(f'{where}: batting runs {bat_runs} + extras {inn["extras"]} ≠ total {inn["runs"]}')
        bowl_balls = sum(r['balls'] for r in bowl)
        if bowl_balls != inn['balls']:
            errors.append(f'{where}: bowlers delivered {overs(bowl_balls)} overs but the innings lasted '
                          f'{overs(inn["balls"])}')
        if sum(r['wickets'] for r in bowl) > inn['wickets']:
            errors.append(f'{where}: bowlers\' wickets exceed innings wickets')
        detail = inn.get('extras_detail')
        if isinstance(detail, dict):
            if sum(detail.values()) != inn['extras']:
                warnings.append(f'{where}: extras breakdown {detail} does not add up to {inn["extras"]}')
            byes = detail.get('b', 0) + detail.get('lb', 0)
            conceded = sum(r['runs'] for r in bowl)
            if conceded != inn['runs'] - byes:
                warnings.append(f'{where}: bowlers conceded {conceded}, expected {inn["runs"] - byes} '
                                '(total minus byes and leg byes); check for penalty runs')
        dismissed = sum(1 for r in bat if not r['not_out'])
        if dismissed != inn['wickets']:
            warnings.append(f'{where}: {dismissed} batters dismissed but {inn["wickets"]} wickets recorded '
                            '(retirements or a source error)')
    return errors, warnings


# --- Database --------------------------------------------------------------------------------

def team_id(db, name):
    db.execute(text('INSERT INTO teams(name) VALUES (:n) ON CONFLICT (name) DO NOTHING'), {'n': name})
    return db.execute(text('SELECT id FROM teams WHERE name = :n'), {'n': name}).scalar_one()


def snapshot(db, match_id):
    """Rebuild the published record for a match from the scorecard tables (None if absent)."""
    m = db.execute(text('SELECT m.*, a.name team1_name, b.name team2_name, w.name winner_name FROM matches m '
                        'JOIN teams a ON a.id=m.team1 JOIN teams b ON b.id=m.team2 JOIN teams w ON w.id=m.winner '
                        'WHERE m.id=:id'), {'id': match_id}).mappings().first()
    if not m:
        return None
    rec = {'id': m['id'], 'date': m['date'].isoformat(), 'venue': m['venue'], 'team1': m['team1_name'],
           'team2': m['team2_name'], 'winner': m['winner_name'], 'result': m['result'], 'toss': m['toss'],
           'pom': m['pom'], 'dls': m['dls'], 'warning': m['warning'], 'stage': m['stage'],
           'source_url': m['source_url'], 'retrieved_at': m['retrieved_at'], 'tournament_id': m['tournament_id'],
           'innings': []}
    for inn in db.execute(text('SELECT i.*, t.name team FROM innings i JOIN teams t ON t.id=i.team_id '
                               'WHERE match_id=:id ORDER BY number'), {'id': match_id}).mappings():
        args = {'id': match_id, 'n': inn['number']}
        rec['innings'].append({
            'team': inn['team'], 'runs': inn['runs'], 'wickets': inn['wickets'], 'balls': inn['balls'],
            'extras': inn['extras'],
            'batting': [dict(r) for r in db.execute(text(
                'SELECT b.player_id, p.name, b.runs, b.balls, b.fours, b.sixes, b.dismissal, b.not_out FROM batting b '
                'JOIN players p ON p.id=b.player_id WHERE match_id=:id AND innings_number=:n ORDER BY position'),
                args).mappings()],
            'bowling': [dict(r) for r in db.execute(text(
                'SELECT b.player_id, p.name, b.balls, b.runs, b.wickets, b.dots, b.wides, b.no_balls FROM bowling b '
                'JOIN players p ON p.id=b.player_id WHERE match_id=:id AND innings_number=:n ORDER BY position'),
                args).mappings()]})
    return rec


def latest_revision(db, match_id):
    return db.execute(text('SELECT number, content_sha256 FROM match_revisions WHERE match_id=:m '
                           'ORDER BY number DESC LIMIT 1'), {'m': match_id}).mappings().first()


def _add_revision(db, record, created_by, batch_id, note):
    current = latest_revision(db, record['id'])
    number = (current['number'] if current else 0) + 1
    content = {k: v for k, v in record.items() if k != 'tournament_id'}
    db.execute(text('INSERT INTO match_revisions(match_id, number, content, content_sha256, created_at, created_by, '
                    'batch_id, note) VALUES (:m, :n, CAST(:c AS jsonb), :h, :at, :by, :b, :note)'),
               {'m': record['id'], 'n': number, 'c': json.dumps(content, ensure_ascii=False), 'h': record_hash(record),
                'at': now(), 'by': created_by, 'b': batch_id, 'note': note})
    return number


def publish(db, record, tournament_id, created_by, batch_id=None, note='', update_player_names=True):
    """Write a fully identified record (every row has player_id) and store it as a new revision.

    Must run inside the caller's transaction. If the match already exists but has no revision
    history (data published before revisions existed), its current state is saved first as a
    baseline revision so it can be restored. Returns the new revision number.
    """
    existing = db.execute(text('SELECT tournament_id FROM matches WHERE id=:id'), {'id': record['id']}).first()
    if existing and existing[0] != tournament_id:
        raise ValueError(f'Match {record["id"]} already belongs to another tournament')
    if existing and not latest_revision(db, record['id']):
        _add_revision(db, snapshot(db, record['id']), 'system', None, 'Baseline: data published before revisions')
    a, b, w = team_id(db, record['team1']), team_id(db, record['team2']), team_id(db, record['winner'])
    db.execute(text(
        'INSERT INTO matches(id,tournament_id,stage,date,venue,team1,team2,winner,result,toss,pom,dls,warning,'
        'source_url,retrieved_at) VALUES (:id,:t,:stage,:date,:venue,:t1,:t2,:w,:result,:toss,:pom,:dls,:warning,'
        ':url,:retrieved) ON CONFLICT (id) DO UPDATE SET stage=excluded.stage,date=excluded.date,'
        'venue=excluded.venue,team1=excluded.team1,team2=excluded.team2,winner=excluded.winner,'
        'result=excluded.result,toss=excluded.toss,pom=excluded.pom,dls=excluded.dls,warning=excluded.warning,'
        'source_url=excluded.source_url,retrieved_at=excluded.retrieved_at'),
        dict(id=record['id'], t=tournament_id, stage=record.get('stage') or '', date=date.fromisoformat(record['date']),
             venue=record['venue'], t1=a, t2=b, w=w, result=record['result'], toss=record.get('toss') or '',
             pom=record.get('pom') or '', dls=bool(record.get('dls')), warning=record.get('warning') or '',
             url=record.get('source_url') or '', retrieved=str(record.get('retrieved_at') or now().isoformat())))
    db.execute(text('DELETE FROM innings WHERE match_id = :id'), {'id': record['id']})
    player_sql = ('INSERT INTO players(id,name) VALUES (:id,:name) ON CONFLICT (id) DO UPDATE SET name=excluded.name'
                  if update_player_names else
                  'INSERT INTO players(id,name) VALUES (:id,:name) ON CONFLICT (id) DO NOTHING')
    for num, inn in enumerate(record['innings'], 1):
        db.execute(text('INSERT INTO innings(match_id,number,team_id,runs,wickets,balls,extras) '
                        'VALUES (:m,:n,:t,:runs,:wk,:balls,:extras)'),
                   dict(m=record['id'], n=num, t=team_id(db, inn['team']), runs=inn['runs'], wk=inn['wickets'],
                        balls=inn['balls'], extras=inn['extras']))
        for pos, r in enumerate(inn['batting'], 1):
            db.execute(text(player_sql), {'id': r['player_id'], 'name': r['name']})
            db.execute(text('INSERT INTO batting(match_id,innings_number,player_id,position,runs,balls,fours,sixes,'
                            'dismissal,not_out) VALUES (:m,:n,:p,:pos,:runs,:balls,:fours,:sixes,:dis,:no)'),
                       dict(m=record['id'], n=num, p=r['player_id'], pos=pos, runs=r['runs'], balls=r['balls'],
                            fours=r['fours'], sixes=r['sixes'], dis=r.get('dismissal') or '', no=r['not_out']))
        for pos, r in enumerate(inn['bowling'], 1):
            db.execute(text(player_sql), {'id': r['player_id'], 'name': r['name']})
            db.execute(text('INSERT INTO bowling(match_id,innings_number,player_id,position,balls,runs,wickets,dots,'
                            'wides,no_balls) VALUES (:m,:n,:p,:pos,:balls,:runs,:wk,:dots,:wd,:nb)'),
                       dict(m=record['id'], n=num, p=r['player_id'], pos=pos, balls=r['balls'], runs=r['runs'],
                            wk=r['wickets'], dots=r['dots'], wd=r['wides'], nb=r['no_balls']))
    return _add_revision(db, record, created_by, batch_id, note)


def is_unchanged(db, record):
    """True when the match's published scorecard already equals this record."""
    current = latest_revision(db, record['id'])
    if current:
        return current['content_sha256'] == record_hash(record)
    published = snapshot(db, record['id'])
    return published is not None and record_hash(published) == record_hash(record)


# --- Differences -----------------------------------------------------------------------------

def diff(old, new):
    """Field-level differences between two records, as [{'field', 'old', 'new'}]."""
    if old is None:
        return []
    changes = []

    def add(field, a, b):
        if a != b:
            changes.append({'field': field, 'old': a, 'new': b})

    for k in MATCH_FIELDS:
        add(k, old.get(k) or ('' if k != 'dls' else False), new.get(k) or ('' if k != 'dls' else False))
    for no, (oi, ni) in enumerate(zip(old['innings'], new['innings']), 1):
        for k in INNINGS_FIELDS:
            add(f'Innings {no} {k}', oi[k], ni[k])
        for kind, fields in (('batting', BATTING_FIELDS), ('bowling', BOWLING_FIELDS)):
            before = {r['player_id']: r for r in oi[kind]}
            after = {r.get('player_id') or ('name:' + r['name']): r for r in ni[kind]}
            for pid, r in after.items():
                if pid not in before:
                    add(f'Innings {no} {kind}: {r["name"]}', 'not listed', 'added')
                    continue
                for k in fields:
                    add(f'Innings {no} {kind}: {r["name"]} {k}', before[pid][k], r[k])
            for pid, r in before.items():
                if pid not in after:
                    add(f'Innings {no} {kind}: {r["name"]}', 'listed', 'removed')
    return changes
