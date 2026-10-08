"""Scorecard JSON bundles (the data/scorecards.json format), the bundled tournament and the seed command.

A bundle is converted to provider-neutral records (see records.py) and checked against the
tournament's playing conditions before any database write. `import_bundle` must be called inside a
transaction (for example `with engine.begin() as conn:`), so a failure leaves statistics unchanged.
"""
import hashlib
import json
import re
from sqlalchemy import text

from ..config import ROOT
from .records import check_record, is_unchanged, now, overs, publish, rules_for, team_id  # noqa: F401

BUNDLED_SCORECARDS = ROOT / 'data/scorecards.json'
BUNDLED_ROSTERS = ROOT / 'data/rosters.json'
BUNDLED_TOURNAMENT = {'external_id': '2194193', 'name': 'Diwhyn Choice T25 Cricket Carnival — Season 2',
                      'slug': 'diwhyn-choice-t25-cricket-carnival-season-2', 'overs_per_innings': 25,
                      'max_overs_per_bowler': 5}
BUNDLED_RULES = rules_for(BUNDLED_TOURNAMENT)


def overs_to_balls(value):
    s = str(value)
    if not re.fullmatch(r'\d+(?:\.[0-5])?', s):
        raise ValueError('Overs must be cricket notation, for example 22.3')
    p = s.split('.')
    return int(p[0]) * 6 + (int(p[1]) if len(p) > 1 else 0)


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


def _innings_record(inn):
    if not isinstance(inn, dict) or not isinstance(inn.get('batting'), list) or not isinstance(inn.get('bowling'), list):
        raise ValueError('Each innings needs team, totals and batting and bowling lists')
    batting = []
    for r in inn['batting']:
        if not isinstance(r, dict):
            raise ValueError('Batting rows must be objects')
        pid = text_field(r.get('player_id'), 'player ID', 20)
        if not pid.isdigit():
            raise ValueError('Player IDs must be numeric CricHeroes IDs')
        if len(r.get('dismissal', '') or '') > 500:
            raise ValueError('Dismissal too long')
        batting.append({'player_id': pid, 'name': text_field(r.get('name'), 'player name', 150),
                        **{k: r.get(k) for k in ('runs', 'balls', 'fours', 'sixes', 'not_out')},
                        'dismissal': r.get('dismissal', '') or ''})
    bowling = []
    for r in inn['bowling']:
        if not isinstance(r, dict):
            raise ValueError('Bowling rows must be objects')
        pid = text_field(r.get('player_id'), 'player ID', 20)
        if not pid.isdigit():
            raise ValueError('Player IDs must be numeric CricHeroes IDs')
        bowling.append({'player_id': pid, 'name': text_field(r.get('name'), 'player name', 150),
                        'balls': overs_to_balls(r.get('overs')),
                        **{k: r.get(k) for k in ('runs', 'wickets', 'dots', 'wides', 'no_balls')}})
    return {'team': inn.get('team'), 'runs': inn.get('runs'), 'wickets': inn.get('wickets'),
            'balls': overs_to_balls(inn.get('overs')), 'extras': inn.get('extras'), 'batting': batting,
            'bowling': bowling}


def bundle_to_records(bundle):
    """Convert a JSON bundle (overs in cricket notation) into records. Raises ValueError on malformed input."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get('matches'), list) or not 1 <= len(bundle['matches']) <= 100:
        raise ValueError('Expected 1–100 scorecards')
    retrieved_at = str(bundle.get('retrieved_at') or now().isoformat(timespec='seconds'))
    records, seen = [], set()
    for m in bundle['matches']:
        if not isinstance(m, dict):
            raise ValueError('Each scorecard must be an object')
        mid = text_field(m.get('id'), 'match ID', 20)
        if not mid.isdigit() or mid in seen:
            raise ValueError('Duplicate or invalid match ID')
        seen.add(mid)
        if not isinstance(m.get('innings'), list):
            raise ValueError('Two innings required')
        records.append({'id': mid, 'date': m.get('date'), 'venue': m.get('venue'), 'team1': m.get('team1'),
                        'team2': m.get('team2'), 'winner': m.get('winner'), 'result': m.get('result'),
                        'toss': m.get('toss', ''), 'pom': m.get('pom', ''), 'dls': bool(m.get('dls', False)),
                        'warning': m.get('warning', ''), 'stage': m.get('stage', ''),
                        'source_url': text_field(m.get('source_url'), 'source URL', 1000), 'retrieved_at': retrieved_at,
                        'innings': [_innings_record(i) for i in m['innings']]})
    return records


def validate(bundle, rules=None):
    """Return the bundle's records, or raise ValueError naming the first problem."""
    rules = rules or BUNDLED_RULES
    records = bundle_to_records(bundle)
    for rec in records:
        errors, _ = check_record(rec, rules)
        if errors:
            raise ValueError(f'Match {rec["id"]}: {errors[0]}')
    return records


def ensure_tournament(db, spec=None):
    """Create the tournament described by spec (default: the bundled one) if missing; return its row."""
    spec = spec or BUNDLED_TOURNAMENT
    db.execute(text('INSERT INTO tournaments(provider, external_id, name, slug, overs_per_innings, max_overs_per_bowler) '
                    'VALUES (:provider, :external_id, :name, :slug, :overs_per_innings, :max_overs_per_bowler) '
                    'ON CONFLICT (provider, external_id) DO NOTHING'), dict({'provider': 'cricheroes'}, **spec))
    return db.execute(text('SELECT * FROM tournaments WHERE provider=:p AND external_id=:e'),
                      {'p': spec.get('provider', 'cricheroes'), 'e': spec['external_id']}).mappings().one()


def import_bundle(db, bundle, source='local JSON', tournament=None, created_by='system'):
    """Validate, then publish every changed match in the bundle (identical matches are left untouched).

    Must run inside a transaction. Returns the number of matches in the bundle.
    """
    tournament = tournament or ensure_tournament(db)
    records = validate(bundle, rules_for(tournament))
    for rec in records:
        if not is_unchanged(db, rec):
            publish(db, rec, tournament['id'], created_by, note=source)
    db.execute(text('INSERT INTO import_log(imported_at,matches,source,content_sha256) VALUES (:at,:n,:src,:h)'),
               {'at': now(), 'n': len(records), 'src': source, 'h': content_hash(bundle)})
    return len(records)


def seed(db):
    """Idempotently load the bundled tournament, club listings and scorecard snapshot.

    Never overwrites an existing match (so later corrections survive a re-run) and never deletes data.
    Returns a dict of what was added.
    """
    roster = json.loads(BUNDLED_ROSTERS.read_text(encoding='utf-8'))
    bundle = json.loads(BUNDLED_SCORECARDS.read_text(encoding='utf-8'))
    tournament = ensure_tournament(db)
    validate(bundle, rules_for(tournament))
    added_listings = 0
    for t in roster['teams']:
        tid = team_id(db, t['name'])
        for p in t['players']:
            added_listings += db.execute(text('INSERT INTO roster_entries VALUES (:t,:n,:s) ON CONFLICT DO NOTHING'),
                                         {'t': tid, 'n': p['name'], 's': roster['source']}).rowcount
    existing = set(db.execute(text('SELECT id FROM matches')).scalars())
    missing = [m for m in bundle['matches'] if m['id'] not in existing]
    if missing:
        import_bundle(db, dict(bundle, matches=missing), 'Bundled public scorecard snapshot', tournament)
    return {'club_listings_added': added_listings, 'matches_added': len(missing),
            'matches_already_present': len(bundle['matches']) - len(missing)}
