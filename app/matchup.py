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
    pivots = {'team': pivot_profile(db, team_id, tournament), 'opponent': pivot_profile(db, opponent_id, tournament)}
    if not any(p['innings_with_fall_of_wickets'] for p in pivots.values()):
        limits.append('No fall-of-wickets data in this scope (only PDF imports carry it), so no pivot-point analysis.')
    return {'scope': scope, 'team': us, 'opponent': them, 'pivots': pivots,
            'head_to_head': head_to_head(db, team_id, opponent_id, tournament),
            'our_batters': ours_bat, 'our_bowlers': ours_bowl, 'their_batters': their_bat, 'their_bowlers': their_bowl,
            'dismissals': dismissal_profiles(db, team_id, opponent_id, tournament), 'data_limits': limits}


# --- Pivot points from fall of wickets -------------------------------------------------------
# Fall of wickets gives the score and over at each wicket (PDF imports only). That supports when
# wickets fell, collapses and partnerships; it does NOT give runs per phase, so none is inferred.

PHASES = (('Overs 1–6', 36), ('Overs 7–15', 90), ('Overs 16+', 10 ** 6))
COLLAPSE_WICKETS, COLLAPSE_RUNS = 3, 15


def phase_of(balls):
    """Over bucket for the ball on which a wicket fell (balls = legal balls bowled when it fell)."""
    return next(name for name, limit in PHASES if balls <= limit)


def collapses(fow):
    """Maximal runs of >= 3 wickets falling for <= 15 runs, measured from the score at which the
    first of them fell (cricket convention: "collapsed from 140/2 to 152/5").
    fow: ordered [{wicket, runs, balls}]."""
    found, i = [], 0
    while i < len(fow):
        start = fow[i]
        j = i
        while j + 1 < len(fow) and fow[j + 1]['runs'] - start['runs'] <= COLLAPSE_RUNS:
            j += 1
        if j - i + 1 >= COLLAPSE_WICKETS:
            found.append({'wickets': j - i + 1, 'runs': fow[j]['runs'] - start['runs'],
                          'from_balls': start['balls'], 'to_balls': fow[j]['balls'],
                          'from': f"{start['runs']}/{start['wicket'] - 1}", 'to': f"{fow[j]['runs']}/{fow[j]['wicket']}",
                          'overs': f"{overs(start['balls'])}–{overs(fow[j]['balls'])}"})
            i = j + 1
        else:
            i += 1
    return found


def partnerships(fow, total_runs, total_balls, wickets):
    rows, prev_r, prev_b = [], 0, 0
    for f in fow:
        rows.append({'wicket': f['wicket'], 'runs': f['runs'] - prev_r, 'balls': f['balls'] - prev_b})
        prev_r, prev_b = f['runs'], f['balls']
    if len(fow) == wickets and wickets < 10:
        rows.append({'wicket': wickets + 1, 'runs': total_runs - prev_r, 'balls': total_balls - prev_b, 'unbroken': True})
    return rows


def _fow_innings(db, team_id, tournament, batting=True):
    """Innings in scope where team_id batted (or bowled), with fall of wickets, newest first."""
    side = 'i.team_id = :t' if batting else 'i.team_id <> :t AND :t IN (m.team1, m.team2)'
    rows = db.execute(text(
        'SELECT i.match_id, i.number, i.runs, i.wickets, i.balls, m.date, tr.overs_per_innings, bt.name batting_team, '
        'ft.name fielding_team FROM innings i JOIN matches m ON m.id=i.match_id JOIN tournaments tr ON tr.id=m.tournament_id '
        'JOIN teams bt ON bt.id=i.team_id JOIN teams ft ON ft.id = CASE WHEN i.team_id=m.team1 THEN m.team2 ELSE m.team1 END '
        f'WHERE {side} AND ' + TF + ' ORDER BY m.date DESC, m.id DESC'), {'t': team_id, 'tour': tournament}).mappings().all()
    out = []
    for r in rows:
        fow = [dict(f) for f in db.execute(text('SELECT wicket, runs, balls, batter FROM fall_of_wickets WHERE match_id=:m '
                                                'AND innings_number=:n ORDER BY wicket'),
                                           {'m': r['match_id'], 'n': r['number']}).mappings()]
        out.append({**dict(r), 'fow': fow})
    return out


def pivot_profile(db, team_id, tournament=None):
    """How a team's innings turn: when its wickets fall, its collapses and partnerships,
    and the collapses it has caused with the ball."""
    batting = _fow_innings(db, team_id, tournament, True)
    bowling = _fow_innings(db, team_id, tournament, False)
    with_fow = [i for i in batting if i['fow']]
    phases = {name: 0 for name, _ in PHASES}
    batting_collapses, parts = [], []
    for inn in with_fow:
        for f in inn['fow']:
            phases[phase_of(f['balls'])] += 1
        for c in collapses(inn['fow']):
            batting_collapses.append({**c, 'against': inn['fielding_team'], 'date': inn['date'].isoformat()})
        for p in partnerships(inn['fow'], inn['runs'], inn['balls'], inn['wickets']):
            parts.append({**p, 'against': inn['fielding_team'], 'date': inn['date'].isoformat()})
    caused = [{**c, 'batting_team': inn['batting_team'], 'date': inn['date'].isoformat()}
              for inn in bowling if inn['fow'] for c in collapses(inn['fow'])]
    top = [p['runs'] for p in parts if p['wicket'] <= 3 and not p.get('unbroken')]
    best = max(parts, key=lambda p: p['runs'], default=None)
    return {'team': _team_name(db, team_id), 'innings_with_fall_of_wickets': len(with_fow), 'innings_total': len(batting),
            'wickets_by_phase': phases, 'collapses': batting_collapses, 'collapses_caused_with_ball': caused,
            'best_partnership': best, 'average_top_order_partnership': round(sum(top) / len(top), 1) if top else None,
            'timelines': [{'against': i['fielding_team'], 'date': i['date'].isoformat(), 'runs': i['runs'],
                           'wickets': i['wickets'], 'balls': i['balls'], 'max_balls': i['overs_per_innings'] * 6,
                           'fow': [{'wicket': f['wicket'], 'runs': f['runs'], 'balls': f['balls'], 'batter': f['batter']}
                                   for f in i['fow']], 'collapses': collapses(i['fow'])}
                          for i in with_fow[:4]]}


def player_card(db, player_id, tournament=None):
    """Profile plus derived shape: batting positions, dismissal types, per-innings series."""
    p = analytics.profile(db, player_id, None, tournament)
    if not p:
        return None
    positions = Counter(b['position'] for b in p['batting_history'])
    kinds = Counter(dismissal_type(b['dismissal']) for b in p['batting_history']
                    if dismissal_type(b['dismissal']) not in ('not out', 'unknown'))
    typical = positions.most_common(1)[0][0] if positions else None
    role = None if typical is None else 'Opener' if typical <= 2 else 'Top order' if typical <= 4 else \
        'Middle order' if typical <= 7 else 'Lower order'
    return {'id': p['id'], 'name': p['name'], 'teams': p['teams'], 'matches': p['matches'],
            'innings': p['innings'], 'runs': p['runs'], 'balls': p['balls'], 'average': p['average'],
            'strike_rate': p['strike_rate'], 'high_score': p['high_score'], 'fours': p['fours'], 'sixes': p['sixes'],
            'boundary_run_pct': p['boundary_run_pct'], 'dismissals': p['dismissals'],
            'wickets': p['wickets'], 'overs': p['overs'], 'economy': p['economy'], 'bowling_balls': p['bowling_balls'],
            'dot_ball_pct': round(p['bowling_dots'] * 100 / p['bowling_balls'], 1) if p['bowling_balls'] else None,
            'batting_role': role, 'batting_positions': dict(sorted(positions.items())),
            'dismissal_types': dict(kinds.most_common()),
            'innings_series': [{'date': b['date'].isoformat(), 'runs': b['runs'], 'balls': b['balls'],
                                'not_out': b['not_out'], 'position': b['position']} for b in p['batting_history']],
            'bowling_series': [{'date': b['date'].isoformat(), 'overs': b['overs'], 'runs': b['runs'],
                                'wickets': b['wickets']} for b in p['bowling_history']],
            'small_sample': p['innings'] < SMALL_SAMPLE}
