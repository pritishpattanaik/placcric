"""Staged imports: upload → preview → admin approval → atomic publish with revisions.

Nothing reaches the scorecard tables until a batch is approved. The raw file is kept privately
under a generated name (its SHA-256) outside the served web directory and outside git.

Players named in a PDF have no provider ID. Each name is identified per team: a name an admin
has already confirmed (player_aliases) resolves automatically; any other name needs a decision
at approval time — link to an existing player, or create a new one. Similar names are offered
as suggestions only and are never merged automatically.
"""
import copy
import difflib
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from sqlalchemy import text

from . import cricheroes_pdf
from .cricheroes_pdf import alias_key, loose_key
from .records import check_record, diff, is_unchanged, now, overs, publish, rules_for, snapshot, team_id
from .scorecards import bundle_to_records, content_hash

MAX_BYTES = {'pdf': 10_000_000, 'json': 2_000_000}
REVIEWER = 'workspace PIN user'  # Replaced by the signed-in Google account in Milestone 2.


class ImportError_(ValueError):
    """A problem the uploader can fix; the message is safe to show."""


# --- Upload ----------------------------------------------------------------------------------

def safe_display_name(filename):
    name = os.path.basename(str(filename or '').replace('\\', '/'))
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()
    return name[:200] or 'upload'


def match_id_from_filename(filename):
    m = re.search(r'(\d{6,20})', filename or '')
    return m[1] if m else ''


def store_raw(upload_dir, data, kind):
    digest = hashlib.sha256(data).hexdigest()
    folder = Path(upload_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'{digest}.{kind}'
    if not path.exists():
        tmp = folder / f'.{digest}.{secrets.token_hex(4)}.partial'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    return digest, path.name


def tournament_row(db, tournament_id):
    row = db.execute(text('SELECT * FROM tournaments WHERE id=:t'), {'t': tournament_id}).mappings().first()
    if not row:
        raise ImportError_('Choose a tournament for this import.')
    return dict(row)


def _same_title(a, b):
    return loose_key(a) == loose_key(b)


def create_batch(engine, upload_dir, data, filename, kind, tournament_id, match_id='', source_url=''):
    """Parse and stage an upload. Returns (batch_id, already_uploaded). Raises ImportError_ for unreadable files."""
    if kind not in MAX_BYTES:
        raise ImportError_('Upload a CricHeroes scorecard PDF or a scorecard JSON file.')
    if not data or len(data) > MAX_BYTES[kind]:
        raise ImportError_(f'{kind.upper()} uploads must be at most {MAX_BYTES[kind] // 1_000_000} MB.')
    filename = safe_display_name(filename)
    with engine.connect() as db:
        tournament = tournament_row(db, tournament_id)
    warnings, source = [], {'kind': kind, 'filename': filename}
    if kind == 'pdf':
        if not data.startswith(b'%PDF-'):
            raise ImportError_('That file is not a PDF.')
        try:
            parsed = cricheroes_pdf.parse(data)
        except cricheroes_pdf.ScorecardPdfError as e:
            raise ImportError_(str(e))
        record = parsed['record']
        record['id'] = str(match_id or '').strip() or match_id_from_filename(filename)
        if not record['id']:
            raise ImportError_('Enter the CricHeroes match ID: the number in the scorecard link, e.g. '
                               '…/scorecard/27466505/….')
        record['source_url'] = str(source_url or '').strip()
        records = [record]
        warnings += parsed['warnings']
        source.update(parsed['source'])
        # A friendly accepts any match, so its PDF title is not expected to match the category name.
        if tournament.get('kind') != 'friendly' and not _same_title(parsed['source']['tournament_title'], tournament['name']):
            warnings.append(f'The PDF says "{parsed["source"]["tournament_title"]}" but you chose the tournament '
                            f'"{tournament["name"]}". Check you picked the right tournament.')
    else:
        try:
            bundle = json.loads(data.decode('utf-8'))
            records = bundle_to_records(bundle)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ImportError_('That file is not valid UTF-8 JSON.')
        except ValueError as e:
            raise ImportError_(f'The JSON file is not in the scorecard format: {e}')
        source['bundle_sha256'] = content_hash(bundle)
    digest, stored = store_raw(upload_dir, data, kind)
    with engine.begin() as db:
        existing = db.execute(text("SELECT id FROM import_batches WHERE file_sha256=:h AND tournament_id=:t "
                                   "AND status IN ('staged','approved') ORDER BY id DESC LIMIT 1"),
                              {'h': digest, 't': tournament_id}).scalar()
        if existing:
            return existing, True
        payload = {'records': records, 'source': source, 'warnings': warnings}
        batch_id = db.execute(text(
            'INSERT INTO import_batches(created_at, created_by, source_kind, original_filename, file_sha256, raw_path, '
            'tournament_id, status, payload) VALUES (:at, :by, :k, :f, :h, :p, :t, \'staged\', CAST(:payload AS jsonb)) '
            'RETURNING id'),
            {'at': now(), 'by': REVIEWER, 'k': kind, 'f': filename, 'h': digest, 'p': stored, 't': tournament_id,
             'payload': json.dumps(payload, ensure_ascii=False)}).scalar_one()
    return batch_id, False


# --- Identities ------------------------------------------------------------------------------

def _rows_by_team(record):
    """Yield (team_name, row, role) for every player row; bowlers belong to the fielding side."""
    teams = [inn['team'] for inn in record['innings']]
    for no, inn in enumerate(record['innings']):
        fielding = teams[1 - no] if len(teams) == 2 else ''
        for r in inn['batting']:
            yield inn['team'], r, 'batting'
        for r in inn['bowling']:
            yield fielding, r, 'bowling'


def _team_players(db, team_name):
    return [dict(r) for r in db.execute(text("""
        SELECT DISTINCT p.id, p.name FROM players p WHERE p.id IN (
          SELECT b.player_id FROM batting b JOIN innings i ON i.match_id=b.match_id AND i.number=b.innings_number
            JOIN teams t ON t.id=i.team_id WHERE t.name=:team
          UNION SELECT b.player_id FROM bowling b JOIN matches m ON m.id=b.match_id
            JOIN teams t ON t.id = CASE WHEN b.innings_number=1 THEN m.team2 ELSE m.team1 END WHERE t.name=:team
          UNION SELECT a.player_id FROM player_aliases a JOIN teams t ON t.id=a.team_id WHERE t.name=:team)
    """), {'team': team_name}).mappings()]


def _suggestions(db, team_name, name, cache):
    if team_name not in cache:
        cache[team_name] = _team_players(db, team_name)
    target = loose_key(name)
    scored = []
    for p in cache[team_name]:
        score = difflib.SequenceMatcher(None, target, loose_key(p['name'])).ratio()
        if score >= 0.6:
            scored.append({'id': p['id'], 'name': p['name'], 'score': round(score, 2), 'same_team': True})
    seen = {s['id'] for s in scored}
    if target:
        for p in db.execute(text('SELECT id, name FROM players')).mappings():
            if p['id'] not in seen and loose_key(p['name']) == target:
                scored.append({'id': p['id'], 'name': p['name'], 'score': 1.0, 'same_team': False})
    return sorted(scored, key=lambda s: (-s['score'], s['name']))[:5]


def identities(db, record):
    """Resolve each named row. Returns {key: identity} where key is 'team|alias'."""
    out, cache = {}, {}
    for team, row, role in _rows_by_team(record):
        if row.get('player_id'):
            continue
        key = f'{team}|{alias_key(row["name"])}'
        if key in out:
            out[key]['roles'].append(role)
            continue
        alias = db.execute(text('SELECT a.player_id, p.name FROM player_aliases a JOIN teams t ON t.id=a.team_id '
                                'JOIN players p ON p.id=a.player_id WHERE t.name=:team AND a.alias_key=:k'),
                           {'team': team, 'k': alias_key(row['name'])}).mappings().first()
        ident = {'key': key, 'team': team, 'name': row['name'], 'roles': [role]}
        if alias:
            ident.update(status='confirmed', player={'id': alias['player_id'], 'name': alias['name']}, suggestions=[])
        else:
            sugg = _suggestions(db, team, row['name'], cache)
            ident.update(status='unresolved', player=None, suggestions=sugg, requires_choice=bool(sugg))
        out[key] = ident
    return out


def _fill_ids(record, resolved):
    rec = copy.deepcopy(record)
    for team, row, _ in _rows_by_team(rec):
        if not row.get('player_id'):
            pid = resolved.get(f'{team}|{alias_key(row["name"])}')
            if pid:
                row['player_id'] = pid
    for inn in rec['innings']:
        for r in inn['batting'] + inn['bowling']:
            r.pop('source_name', None)
    return rec


# --- Preview ---------------------------------------------------------------------------------

def _load_batch(db, batch_id, lock=False):
    row = db.execute(text('SELECT b.*, t.name tournament_name FROM import_batches b JOIN tournaments t '
                          'ON t.id=b.tournament_id WHERE b.id=:id' + (' FOR UPDATE OF b' if lock else '')),
                     {'id': batch_id}).mappings().first()
    if not row:
        raise LookupError('Import not found')
    return dict(row)


def _analyse(db, batch):
    tournament = tournament_row(db, batch['tournament_id'])
    rules = rules_for(tournament)
    payload = batch['payload']
    errors, warnings, matches = [], list(payload.get('warnings', [])), []
    for record in payload['records']:
        idents = identities(db, record)
        resolved = {k: v['player']['id'] for k, v in idents.items() if v['status'] == 'confirmed'}
        filled = _fill_ids(record, resolved)
        rec_errors, rec_warnings = check_record(record, rules, require_player_ids=False)
        published = snapshot(db, record['id']) if re.fullmatch(r'\d{1,20}', str(record['id'])) else None
        if published and published['tournament_id'] != tournament['id']:
            rec_errors.append(f'Match {record["id"]} is already published in a different tournament.')
        complete = all(v['status'] == 'confirmed' for v in idents.values())
        unchanged = bool(published) and complete and is_unchanged(db, filled)
        prefix = f'Match {record["id"] or "?"}: ' if len(payload['records']) > 1 else ''
        errors += [prefix + e for e in rec_errors]
        warnings += [prefix + w for w in rec_warnings]
        matches.append({
            'id': record['id'], 'date': record['date'], 'stage': record.get('stage', ''), 'venue': record['venue'],
            'team1': record['team1'], 'team2': record['team2'], 'result': record['result'],
            'toss': record.get('toss', ''), 'source_url': record.get('source_url', ''),
            'innings': [{'team': i['team'], 'runs': i['runs'], 'wickets': i['wickets'], 'overs': overs(i['balls']),
                         'extras': i['extras'], 'batters': len(i['batting']), 'bowlers': len(i['bowling'])}
                        for i in record['innings']],
            'status': 'new' if not published else ('unchanged' if unchanged else 'correction'),
            'changes': diff(published, filled) if published else [],
            'identities': list(idents.values())})
    return {'errors': errors, 'warnings': warnings, 'matches': matches, 'rules': rules}


def preview(db, batch_id):
    batch = _load_batch(db, batch_id)
    analysis = _analyse(db, batch)
    return {'id': batch['id'], 'status': batch['status'], 'created_at': batch['created_at'],
            'created_by': batch['created_by'], 'reviewed_at': batch['reviewed_at'], 'reviewed_by': batch['reviewed_by'],
            'kind': batch['source_kind'], 'filename': batch['original_filename'], 'file_sha256': batch['file_sha256'],
            'tournament': {'id': batch['tournament_id'], 'name': batch['tournament_name']},
            'source': batch['payload'].get('source', {}), 'outcome': batch['payload'].get('outcome'),
            'approvable': batch['status'] == 'staged' and not analysis['errors'],
            'rules': {k: analysis['rules'][k] for k in ('overs_per_innings', 'max_overs_per_bowler')},
            'errors': analysis['errors'], 'warnings': analysis['warnings'], 'matches': analysis['matches']}


def list_batches(db, limit=30):
    rows = db.execute(text('SELECT b.id, b.created_at, b.source_kind, b.original_filename, b.status, b.reviewed_at, '
                           't.name tournament_name, b.payload FROM import_batches b JOIN tournaments t '
                           'ON t.id=b.tournament_id ORDER BY b.id DESC LIMIT :n'), {'n': limit}).mappings()
    return [{**{k: r[k] for k in ('id', 'created_at', 'source_kind', 'original_filename', 'status', 'reviewed_at',
                                  'tournament_name')},
             'match_ids': [rec['id'] for rec in r['payload']['records']]} for r in rows]


# --- Approve / reject ------------------------------------------------------------------------

def _new_player(db, name, cricheroes_id):
    if cricheroes_id:
        if not re.fullmatch(r'\d{1,20}', cricheroes_id):
            raise ImportError_(f'CricHeroes player ID for {name} must be a number.')
        if db.execute(text('SELECT 1 FROM players WHERE id=:id'), {'id': cricheroes_id}).first():
            raise ImportError_(f'Player ID {cricheroes_id} already exists; choose "link" for {name} instead.')
        db.execute(text("INSERT INTO players(id, name, provider) VALUES (:id, :n, 'cricheroes')"),
                   {'id': cricheroes_id, 'n': name})
        return cricheroes_id
    pid = 'pc-' + secrets.token_hex(6)
    db.execute(text("INSERT INTO players(id, name, provider) VALUES (:id, :n, 'placcric')"), {'id': pid, 'n': name})
    return pid


def approve(engine, batch_id, decisions=None, reviewer=REVIEWER):
    """Resolve identities with the given decisions and publish every record in one transaction.

    decisions: {identity_key: {'action': 'link', 'player_id': …} | {'action': 'new', 'cricheroes_id': '…'?}}.
    An unresolved name with suggestions must have a decision; one without suggestions defaults to
    a new player. Returns the outcome stored on the batch.
    """
    decisions = decisions or {}
    if not isinstance(decisions, dict):
        raise ImportError_('Invalid identity decisions.')
    with engine.begin() as db:
        batch = _load_batch(db, batch_id, lock=True)
        if batch['status'] != 'staged':
            raise ImportError_(f'This import is already {batch["status"]}.')
        analysis = _analyse(db, batch)
        if analysis['errors']:
            raise ImportError_('Fix the listed errors before approving: ' + analysis['errors'][0])
        outcome = []
        for record, info in zip(batch['payload']['records'], analysis['matches']):
            resolved = {}
            for ident in info['identities']:
                if ident['status'] == 'confirmed':
                    resolved[ident['key']] = ident['player']['id']
                    continue
                d = decisions.get(ident['key']) or {}
                action = d.get('action') or ('' if ident.get('requires_choice') else 'new')
                if action == 'link':
                    pid = str(d.get('player_id') or '')
                    if not db.execute(text('SELECT 1 FROM players WHERE id=:id'), {'id': pid}).first():
                        raise ImportError_(f'Choose an existing player for {ident["name"]} ({ident["team"]}).')
                elif action == 'new':
                    pid = _new_player(db, ident['name'], str(d.get('cricheroes_id') or '').strip())
                else:
                    raise ImportError_(f'Decide who "{ident["name"]}" ({ident["team"]}) is: link to a suggested '
                                       'player or create a new one.')
                db.execute(text('INSERT INTO player_aliases(team_id, alias_key, display_name, player_id, batch_id, '
                                'created_at) VALUES (:t, :k, :n, :p, :b, :at) ON CONFLICT DO NOTHING'),
                           {'t': team_id(db, ident['team']), 'k': ident['key'].split('|', 1)[1], 'n': ident['name'],
                            'p': pid, 'b': batch_id, 'at': now()})
                resolved[ident['key']] = pid
            filled = _fill_ids(record, resolved)
            errors, _ = check_record(filled, analysis['rules'])
            if errors:
                raise ImportError_(errors[0])
            if is_unchanged(db, filled):
                outcome.append({'match_id': filled['id'], 'result': 'unchanged'})
            else:
                number = publish(db, filled, batch['tournament_id'], reviewer, batch_id,
                                 note=f'{batch["source_kind"].upper()} import #{batch_id}: {batch["original_filename"]}',
                                 update_player_names=batch['source_kind'] == 'json')
                outcome.append({'match_id': filled['id'], 'result': 'published', 'revision': number})
        db.execute(text('INSERT INTO import_log(imported_at, matches, source, content_sha256) VALUES (:at, :n, :s, :h)'),
                   {'at': now(), 'n': len(outcome), 'h': batch['file_sha256'],
                    's': f'{batch["source_kind"].upper()} import #{batch_id}: {batch["original_filename"]}'})
        payload = dict(batch['payload'], outcome=outcome)
        db.execute(text("UPDATE import_batches SET status='approved', reviewed_at=:at, reviewed_by=:by, "
                        "payload=CAST(:p AS jsonb) WHERE id=:id"),
                   {'at': now(), 'by': reviewer, 'p': json.dumps(payload, ensure_ascii=False), 'id': batch_id})
    return outcome


def reject(engine, batch_id, reviewer=REVIEWER):
    with engine.begin() as db:
        batch = _load_batch(db, batch_id, lock=True)
        if batch['status'] != 'staged':
            raise ImportError_(f'This import is already {batch["status"]}.')
        db.execute(text("UPDATE import_batches SET status='rejected', reviewed_at=:at, reviewed_by=:by WHERE id=:id"),
                   {'at': now(), 'by': reviewer, 'id': batch_id})


# --- Revisions -------------------------------------------------------------------------------

def revisions(db, match_id):
    return [dict(r) for r in db.execute(text(
        'SELECT r.number, r.created_at, r.created_by, r.note, r.batch_id, r.content_sha256, '
        '(SELECT max(number) FROM match_revisions WHERE match_id=:m) = r.number AS current '
        'FROM match_revisions r WHERE r.match_id=:m ORDER BY r.number DESC'), {'m': match_id}).mappings()]


def restore(engine, match_id, number, reviewer=REVIEWER):
    """Republish an earlier revision as a new revision. Returns the new revision number (or None if unchanged)."""
    with engine.begin() as db:
        row = db.execute(text('SELECT r.content, m.tournament_id FROM match_revisions r JOIN matches m ON m.id=r.match_id '
                              'WHERE r.match_id=:m AND r.number=:n'), {'m': match_id, 'n': number}).mappings().first()
        if not row:
            raise LookupError('Revision not found')
        if is_unchanged(db, row['content']):
            return None
        return publish(db, row['content'], row['tournament_id'], reviewer, note=f'Restored revision {number}',
                       update_player_names=False)
