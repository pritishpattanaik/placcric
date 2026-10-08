"""Team-against-team analysis for the Captain's room, computed only from imported scorecards.

Everything here is deterministic. Dismissal types and "who dismissed whom" come from the dismissal
text in each batting row (e.g. "c Ian Nine b Jo Ten"), matched to a bowler in the *same* innings by
exact cleaned name; nothing is inferred across matches by name. There is no ball-by-ball data, so
there are no phase, line/length or batter-versus-bowler ball counts.
"""
import re
from collections import Counter, defaultdict

from sqlalchemy import text

from . import analytics
from .ingestion.cricheroes_pdf import clean_name
from .ingestion.records import overs

TF = analytics.TF
SMALL_SAMPLE = 3

DISMISSAL_TYPES = (('run out', r'^run out\b'), ('lbw', r'^lbw\b'), ('stumped', r'^st\b'),
                   ('caught and bowled', r'^c\s*&\s*b\b'), ('caught', r'^c\b'), ('bowled', r'^b\b'),
                   ('hit wicket', r'^hit wicket\b'), ('not out', r'^(not out|retired hurt|retired not out)\b'))


def dismissal_type(text_):
    t = (text_ or '').strip().lower()
    for name, pattern in DISMISSAL_TYPES:
        if re.match(pattern, t):
            return name
    return 'other' if t else 'unknown'


def credited_bowler(text_):
    """Bowler name credited with the wicket, or None (run outs and not-outs credit no bowler)."""
    t = (text_ or '').strip()
    if dismissal_type(t) in ('run out', 'not out', 'other', 'unknown'):
        return None
    m = re.search(r'(?:^|\s)(?:c\s*&\s*)?b\s+(.+)$', t)
    return clean_name(m[1]) if m else None


def _rate(runs, balls):
    return round(runs * 6 / balls, 2) if balls else None


def _team_name(db, team_id):
    return db.execute(text('SELECT name FROM teams WHERE id=:t'), {'t': team_id}).scalar()


def team_profile(db, team_id, tournament=None):
    matches = analytics.match_list(db, team_id, tournament)
    played, won, bat_first, bat_first_won, scores, form = len(matches), 0, 0, 0, [], []
    runs_for = balls_for = wkts_lost = runs_against = balls_against = wkts_taken = 0
    for m in sorted(matches, key=lambda m: (m['date'], m['id'])):
        win = m['winner'] == team_id
        won += win
        form.append('W' if win else 'L')
        for i in m['innings']:
            if i['team_id'] == team_id:
                runs_for += i['runs']; balls_for += i['balls']; wkts_lost += i['wickets']
                scores.append(i['runs'])
                if i['number'] == 1:
                    bat_first += 1
                    bat_first_won += win
            else:
                runs_against += i['runs']; balls_against += i['balls']; wkts_taken += i['wickets']
    return {
        'team': _team_name(db, team_id), 'matches': played, 'won': won, 'lost': played - won,
        'batting_first': {'played': bat_first, 'won': bat_first_won},
        'chasing': {'played': played - bat_first, 'won': won - bat_first_won},
        'average_score': round(sum(scores) / len(scores), 1) if scores else None,
        'highest_score': max(scores, default=None), 'lowest_score': min(scores, default=None),
        'run_rate': _rate(runs_for, balls_for), 'average_wickets_lost': round(wkts_lost / played, 1) if played else None,
        'runs_conceded_per_over': _rate(runs_against, balls_against),
        'average_wickets_taken': round(wkts_taken / played, 1) if played else None,
        'recent_form': form[-5:], 'small_sample': played < SMALL_SAMPLE,
    }


def _player_lines(db, team_id, tournament):
    ps = analytics.players(db, team_id, tournament)
    bat = sorted([p for p in ps if p['innings']], key=lambda p: (-p['runs'], p['name']))[:5]
    bowl = sorted([p for p in ps if p['bowling_balls']], key=lambda p: (-p['wickets'], p['economy'] or 99, p['name']))[:5]
    return ([{'name': p['name'], 'innings': p['innings'], 'runs': p['runs'], 'balls': p['balls'], 'strike_rate': p['strike_rate'],
              'average': p['average'], 'high_score': p['high_score'], 'fours': p['fours'], 'sixes': p['sixes']} for p in bat],
            [{'name': p['name'], 'overs': p['overs'], 'wickets': p['wickets'], 'economy': p['economy'],
              'dot_ball_pct': round(p['bowling_dots'] * 100 / p['bowling_balls'], 1) if p['bowling_balls'] else None}
             for p in bowl])


def _innings_rows(db, tournament):
    """Every batting row in scope with its batting team, fielding team and the bowlers of that innings."""
    rows = db.execute(text(
        'SELECT b.match_id, b.innings_number, b.player_id, p.name, b.dismissal, b.not_out, b.runs, b.balls, i.team_id bat_team, '
        'CASE WHEN i.team_id=m.team1 THEN m.team2 ELSE m.team1 END field_team FROM batting b '
        'JOIN innings i ON i.match_id=b.match_id AND i.number=b.innings_number JOIN matches m ON m.id=b.match_id '
        'JOIN players p ON p.id=b.player_id WHERE ' + TF), {'tour': tournament}).mappings().all()
    # A bowler is recognised in dismissal text by their stored name or by a scorecard spelling an admin confirmed.
    spellings = defaultdict(set)
    for a in db.execute(text('SELECT player_id, display_name FROM player_aliases')).mappings():
        spellings[a['player_id']].add(clean_name(a['display_name']).casefold())
    bowlers = defaultdict(dict)
    for r in db.execute(text('SELECT b.match_id, b.innings_number, b.player_id, p.name FROM bowling b JOIN matches m '
                             'ON m.id=b.match_id JOIN players p ON p.id=b.player_id WHERE ' + TF), {'tour': tournament}).mappings():
        for spelling in {clean_name(r['name']).casefold()} | spellings[r['player_id']]:
            bowlers[(r['match_id'], r['innings_number'])][spelling] = (r['player_id'], r['name'])
    return rows, bowlers


def dismissal_profiles(db, team_id, opponent_id, tournament=None):
    rows, bowlers = _innings_rows(db, tournament)
    how_out = {team_id: Counter(), opponent_id: Counter()}
    wicket_types = {team_id: Counter(), opponent_id: Counter()}
    direct = Counter()
    names = {}
    for r in rows:
        kind = dismissal_type(r['dismissal'])
        if r['bat_team'] in how_out and kind not in ('not out', 'unknown'):
            how_out[r['bat_team']][kind] += 1
        if r['field_team'] in wicket_types and kind not in ('not out', 'unknown', 'run out', 'other'):
            wicket_types[r['field_team']][kind] += 1
        name = credited_bowler(r['dismissal'])
        bowler = bowlers[(r['match_id'], r['innings_number'])].get(name.casefold()) if name else None
        if bowler and {r['bat_team'], r['field_team']} == {team_id, opponent_id}:
            direct[(bowler[0], r['player_id'], r['field_team'])] += 1
            names[bowler[0]], names[r['player_id']] = bowler[1], r['name']
    return {
        'how_batters_get_out': {_team_name(db, t): dict(c.most_common()) for t, c in how_out.items()},
        'how_bowlers_take_wickets': {_team_name(db, t): dict(c.most_common()) for t, c in wicket_types.items()},
        'head_to_head_dismissals': [
            {'bowler': names[b], 'bowler_team': _team_name(db, ft), 'batter': names[bat], 'times': n}
            for (b, bat, ft), n in sorted(direct.items(), key=lambda kv: (-kv[1], names[kv[0][0]]))],
    }


def head_to_head(db, team_id, opponent_id, tournament=None):
    return [{'date': m['date'].isoformat(), 'tournament': m['tournament_name'], 'stage': m['stage'], 'result': m['result'],
             'winner': _team_name(db, m['winner']),
             'scores': [f"{i['team_name']} {i['runs']}/{i['wickets']} ({overs(i['balls'])} ov)" for i in m['innings']],
             'match_id': m['id']}
            for m in analytics.match_list(db, team_id, tournament) if opponent_id in (m['team1'], m['team2'])]


def matchup(db, team_id, opponent_id, tournament=None):
    if team_id == opponent_id:
        raise ValueError('Choose two different teams')
    for t in (team_id, opponent_id):
        if not _team_name(db, t):
            raise ValueError('Unknown team')
    ours_bat, ours_bowl = _player_lines(db, team_id, tournament)
    their_bat, their_bowl = _player_lines(db, opponent_id, tournament)
    scope = 'All tournaments and friendlies'
    if tournament:
        scope = db.execute(text('SELECT name FROM tournaments WHERE id=:t'), {'t': tournament}).scalar() or scope
    us, them = team_profile(db, team_id, tournament), team_profile(db, opponent_id, tournament)
    limits = ['No ball-by-ball data: no phase (powerplay/death) splits, no batter-versus-bowler ball counts, '
              'no line, length, pace or spin information.',
              'Dismissal matchups come only from the dismissal text of imported scorecards.']
    for p in (us, them):
        if p['small_sample']:
            limits.append(f"{p['team']}: only {p['matches']} imported match(es); treat trends as weak evidence.")
    return {'scope': scope, 'team': us, 'opponent': them,
            'head_to_head': head_to_head(db, team_id, opponent_id, tournament),
            'our_batters': ours_bat, 'our_bowlers': ours_bowl, 'their_batters': their_bat, 'their_bowlers': their_bowl,
            'dismissals': dismissal_profiles(db, team_id, opponent_id, tournament), 'data_limits': limits}
