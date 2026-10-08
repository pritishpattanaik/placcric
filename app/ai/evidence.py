"""Evidence packs: the only data sent to the AI model.

Each pack is built on the server from imported scorecards (the browser cannot supply its own
numbers). Packs contain team names, player names and statistics. They never contain player or
match IDs, the PIN, sessions, file contents or uploaded PDFs. Captain notes are included only when
the user ticks "include my match plan".
"""
from sqlalchemy import text

from .. import analytics, matchup
from ..ingestion.records import overs


def _scope(db, tournament):
    if not tournament:
        return 'All tournaments and friendlies'
    return db.execute(text('SELECT name FROM tournaments WHERE id=:t'), {'t': tournament}).scalar() or 'Unknown'


def _strip_ids(report):
    """Head-to-head entries carry match IDs for the UI; the model does not need them."""
    out = dict(report)
    out['head_to_head'] = [{k: v for k, v in m.items() if k != 'match_id'} for m in report['head_to_head']]
    return out


def matchup_pack(db, team_id, opponent_id, tournament=None, include_notes=False):
    pack = _strip_ids(matchup.matchup(db, team_id, opponent_id, tournament))
    if include_notes:
        note = db.execute(text('SELECT body FROM notes WHERE team_id=:t'), {'t': team_id}).scalar()
        pack['our_match_plan_notes'] = (note or '')[:4000]
    return pack


def player_pack(db, player_id, tournament=None):
    p = analytics.profile(db, player_id, None, tournament)
    if not p:
        raise LookupError('Player not found in the selected scope')
    batting = [{'date': b['date'].isoformat(), 'team': b['team_name'], 'runs': b['runs'], 'balls': b['balls'],
                'fours': b['fours'], 'sixes': b['sixes'], 'not_out': b['not_out'],
                'dismissal_type': matchup.dismissal_type(b['dismissal']), 'dismissal': b['dismissal']}
               for b in p['batting_history']]
    bowling = [{'date': b['date'].isoformat(), 'overs': overs(b['balls']), 'runs': b['runs'], 'wickets': b['wickets'],
                'dots': b['dots'], 'wides': b['wides'], 'no_balls': b['no_balls']} for b in p['bowling_history']]
    return {'scope': _scope(db, tournament), 'player': p['name'], 'teams': p['teams'], 'matches': p['matches'],
            'batting': {'innings': p['innings'], 'runs': p['runs'], 'balls': p['balls'], 'dismissals': p['dismissals'],
                        'average': p['average'], 'strike_rate': p['strike_rate'], 'high_score': p['high_score'],
                        'fours': p['fours'], 'sixes': p['sixes'], 'boundary_run_pct': p['boundary_run_pct'],
                        'by_innings': batting},
            'bowling': {'overs': p['overs'], 'wickets': p['wickets'], 'runs': p['bowling_runs'], 'economy': p['economy'],
                        'dots': p['bowling_dots'], 'by_match': bowling},
            'data_limits': ['Imported scorecards only; no ball-by-ball, video, phase or pace/spin data.'] +
                           ([f"Only {p['innings']} batting innings: far too few for stable conclusions."]
                            if p['innings'] < matchup.SMALL_SAMPLE else [])}


def compare_pack(db, player_a, player_b, tournament=None):
    if player_a == player_b:
        raise ValueError('Choose two different players')
    return {'scope': _scope(db, tournament), 'players': [player_pack(db, player_a, tournament),
                                                         player_pack(db, player_b, tournament)]}
