"""One-time copy of a legacy PlacCric SQLite database (schema user_version 1) into PostgreSQL.

* The SQLite file is opened read-only and its SHA-256 is checked before and after.
* Cricket data, club listings, notes and import history are copied with their original IDs.
* PIN hashes (`auth`), sessions, login attempts and `meta` are deliberately NOT copied.
* The target must be migrated to the latest schema and contain no cricket data.
* Everything runs in one PostgreSQL transaction. Row counts, aggregate totals and a per-table
  content digest are compared before commit; any mismatch rolls back. `dry_run` always rolls back.
"""
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from .ingestion.scorecards import ensure_tournament
from .models import CRICKET_TABLES

# (table, columns in copy order, boolean columns, primary key for deterministic ordering)
TABLES = [
    ('teams', ['id', 'name'], [], ['id']),
    ('players', ['id', 'name'], [], ['id']),
    ('roster_entries', ['team_id', 'name', 'source_url'], [], ['team_id', 'name']),
    ('matches', ['id', 'date', 'venue', 'team1', 'team2', 'winner', 'result', 'toss', 'pom', 'dls', 'warning',
                 'source_url', 'retrieved_at'], ['dls'], ['id']),
    ('innings', ['match_id', 'number', 'team_id', 'runs', 'wickets', 'balls', 'extras'], [], ['match_id', 'number']),
    ('batting', ['match_id', 'innings_number', 'player_id', 'position', 'runs', 'balls', 'fours', 'sixes', 'dismissal',
                 'not_out'], ['not_out'], ['match_id', 'innings_number', 'player_id']),
    ('bowling', ['match_id', 'innings_number', 'player_id', 'position', 'balls', 'runs', 'wickets', 'dots', 'wides',
                 'no_balls'], [], ['match_id', 'innings_number', 'player_id']),
    ('notes', ['team_id', 'body', 'updated_at'], [], ['team_id']),
    ('import_log', ['id', 'imported_at', 'matches', 'source'], [], ['id']),
]
NOT_MIGRATED = ('auth', 'sessions', 'login_attempts', 'meta')
AGGREGATES = {
    'innings': ['runs', 'wickets', 'balls', 'extras'],
    'batting': ['runs', 'balls', 'fours', 'sixes', 'not_out'],
    'bowling': ['balls', 'runs', 'wickets', 'dots', 'wides', 'no_balls'],
    'import_log': ['matches'],
}
SEQUENCES = {'teams': 'id', 'import_log': 'id'}


class MigrationError(RuntimeError):
    pass


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def open_readonly(path):
    uri = 'file:' + quote(str(Path(path).resolve())) + '?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    return db


def parse_timestamp(value, field):
    try:
        ts = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        raise MigrationError(f'{field} has an unreadable timestamp: {value!r}')
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def convert(table, row, booleans):
    out = dict(row)
    for b in booleans:
        if out[b] not in (0, 1):
            raise MigrationError(f'{table}.{b} must be 0 or 1, found {out[b]!r}')
        out[b] = bool(out[b])
    if table == 'matches':
        out['date'] = date.fromisoformat(out['date'])
        for k in ('toss', 'pom', 'warning'):
            out[k] = out[k] or ''
    if table == 'batting':
        out['dismissal'] = out['dismissal'] or ''
    if table == 'notes':
        out['updated_at'] = parse_timestamp(out['updated_at'], 'notes.updated_at')
    if table == 'import_log':
        out['imported_at'] = parse_timestamp(out['imported_at'], 'import_log.imported_at')
    return out


def normalise(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def digest_rows(rows, columns):
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps([normalise(r[c]) for c in columns], ensure_ascii=False).encode('utf-8'))
    return h.hexdigest()


def summarise(rows_by_table):
    """Counts, aggregate totals and a content digest per table, from already-converted rows."""
    out = {}
    for table, columns, _, key in TABLES:
        rows = sorted(rows_by_table[table], key=lambda r: tuple(normalise(r[k]) for k in key))
        out[table] = {'rows': len(rows),
                      'totals': {c: sum(int(r[c]) for r in rows) for c in AGGREGATES.get(table, [])},
                      'digest': digest_rows(rows, columns)}
    return out


def read_source(path):
    db = open_readonly(path)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version != 1:
            raise MigrationError(f'Unsupported SQLite schema version {version}; expected 1.')
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = {}
        for table, columns, booleans, _ in TABLES:
            if table not in present:
                raise MigrationError(f'SQLite database is missing table {table}.')
            have = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            missing = [c for c in columns if c not in have]
            if missing:
                raise MigrationError(f'SQLite table {table} is missing columns: {", ".join(missing)}.')
            rows[table] = [convert(table, r, booleans) for r in db.execute(f'SELECT {", ".join(columns)} FROM {table}')]
        skipped = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in NOT_MIGRATED if t in present}
        return rows, skipped
    finally:
        db.close()


def read_target(conn):
    rows = {}
    for table, columns, _, _ in TABLES:
        rows[table] = [dict(r) for r in conn.execute(text(f'SELECT {", ".join(columns)} FROM {table}')).mappings()]
    return rows


def compare(source, target):
    """Return a list of human-readable differences between two summaries."""
    problems = []
    for table in source:
        s, t = source[table], target[table]
        if s['rows'] != t['rows']:
            problems.append(f'{table}: {s["rows"]} source rows but {t["rows"]} copied')
        for col, total in s['totals'].items():
            if t['totals'].get(col) != total:
                problems.append(f'{table}.{col}: source total {total} but copied total {t["totals"].get(col)}')
        if s['digest'] != t['digest']:
            problems.append(f'{table}: copied content differs from source')
    return problems


def migrate(sqlite_path, engine, database_url, dry_run=False):
    from .db import schema_status

    sqlite_path = Path(sqlite_path)
    if not sqlite_path.is_file():
        raise MigrationError(f'SQLite file not found: {sqlite_path}')
    before = file_sha256(sqlite_path)
    source_rows, skipped = read_source(sqlite_path)
    source_summary = summarise(source_rows)

    current, head, ok = schema_status(engine, database_url)
    if not ok:
        raise MigrationError(f'PostgreSQL schema is at {current or "no revision"}, expected {head}. '
                             'Run `python3 -m app.cli db-upgrade` first.')
    conn = engine.connect()
    trans = conn.begin()
    try:
        # The built-in "Friendly Match" category (migration 0003) is not user data.
        occupied = [t for t in CRICKET_TABLES if conn.execute(text(
            f"SELECT EXISTS (SELECT 1 FROM {t}" + (" WHERE kind <> 'friendly')" if t == 'tournaments' else ')'))).scalar_one()]
        if occupied:
            raise MigrationError('Target PostgreSQL database already contains data in: ' + ', '.join(occupied) +
                                 '. Migrate into a freshly upgraded, unseeded database.')
        # Every legacy match belongs to the bundled tournament (schema user_version 1 had no tournaments).
        tournament_id = ensure_tournament(conn)['id']
        for table, columns, _, _ in TABLES:
            if source_rows[table]:
                rows, cols = source_rows[table], columns
                if table == 'matches':
                    rows, cols = [dict(r, tournament_id=tournament_id) for r in rows], columns + ['tournament_id']
                conn.execute(text(f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({", ".join(":" + c for c in cols)})'),
                             rows)
        for table, column in SEQUENCES.items():
            conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                              f"COALESCE((SELECT max({column}) FROM {table}), 0) + 1, false)"))
        target_summary = summarise(read_target(conn))
        problems = compare(source_summary, target_summary)
        if problems:
            raise MigrationError('Verification failed; nothing was written:\n  ' + '\n  '.join(problems))
        if dry_run:
            trans.rollback()
        else:
            trans.commit()
    except BaseException:
        if trans.is_active:
            trans.rollback()
        raise
    finally:
        conn.close()
    after = file_sha256(sqlite_path)
    if after != before:
        raise MigrationError('The SQLite file changed during migration (was the old server still running?). '
                             'PostgreSQL ' + ('was not modified.' if dry_run else 'data was committed; verify it.'))
    return {'dry_run': dry_run, 'committed': not dry_run, 'sqlite_sha256': before, 'tables': target_summary,
            'not_migrated': skipped}
