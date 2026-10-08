"""Builds a database in the legacy SQLite MVP format (schema user_version 1) for migration tests."""
import json
import sqlite3
from pathlib import Path

from app.ingestion.scorecards import BUNDLED_ROSTERS, BUNDLED_SCORECARDS, overs_to_balls

SCHEMA = Path(__file__).with_name('fixtures') / 'legacy_sqlite_schema.sql'


def build(path, team_id_offset=0):
    """Populate like the legacy initialize(); team IDs can be offset to prove IDs are preserved, not renumbered."""
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA.read_text())
    roster = json.loads(BUNDLED_ROSTERS.read_text())
    bundle = json.loads(BUNDLED_SCORECARDS.read_text())
    ids = {}

    def tid(name):
        if name not in ids:
            ids[name] = len(ids) * 3 + 1 + team_id_offset
            db.execute('INSERT INTO teams(id,name) VALUES(?,?)', (ids[name], name))
        return ids[name]

    with db:
        for t in roster['teams']:
            i = tid(t['name'])
            for p in t['players']:
                db.execute('INSERT OR IGNORE INTO roster_entries VALUES(?,?,?)', (i, p['name'], roster['source']))
        for m in bundle['matches']:
            db.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (m['id'], m['date'], m['venue'], tid(m['team1']), tid(m['team2']), tid(m['winner']), m['result'],
                        m.get('toss', ''), m.get('pom', ''), int(m.get('dls', False)), m.get('warning', ''),
                        m['source_url'], bundle['retrieved_at']))
            for num, inn in enumerate(m['innings'], 1):
                db.execute('INSERT INTO innings VALUES(?,?,?,?,?,?,?)', (m['id'], num, tid(inn['team']), inn['runs'],
                                                                          inn['wickets'], overs_to_balls(inn['overs']), inn['extras']))
                for kind in ('batting', 'bowling'):
                    for pos, r in enumerate(inn[kind], 1):
                        db.execute('INSERT INTO players VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',
                                   (r['player_id'], r['name']))
                        if kind == 'batting':
                            db.execute('INSERT INTO batting VALUES(?,?,?,?,?,?,?,?,?,?)',
                                       (m['id'], num, r['player_id'], pos, r['runs'], r['balls'], r['fours'], r['sixes'],
                                        r.get('dismissal', ''), int(r['not_out'])))
                        else:
                            db.execute('INSERT INTO bowling VALUES(?,?,?,?,?,?,?,?,?,?)',
                                       (m['id'], num, r['player_id'], pos, overs_to_balls(r['overs']), r['runs'],
                                        r['wickets'], r['dots'], r['wides'], r['no_balls']))
        db.execute('INSERT INTO import_log(id,imported_at,matches,source) VALUES(4,?,5,?)',
                   ('2026-10-07T09:00:00+00:00', 'Bundled verified public scorecards'))
        ucc = ids['UTKAL Cricket Club (UCC).']
        db.execute('INSERT INTO notes VALUES(?,?,?)', (ucc, 'Open with spin; accents é, emoji 🏏 preserved', '2026-10-07T10:30:00+00:00'))
        db.execute("INSERT INTO meta VALUES('seeded','1')")
        db.execute("INSERT INTO auth VALUES(1,'00','legacyhash')")
        db.execute("INSERT INTO sessions VALUES('legacytoken','csrf',9999999999)")
        db.execute("INSERT INTO login_attempts VALUES('127.0.0.1',1)")
    db.close()
    return ids
