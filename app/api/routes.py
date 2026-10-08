"""JSON API. Every route except /api/session and /api/login requires a session; POSTs also require CSRF."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import analytics
from ..auth import pin
from ..ingestion.scorecards import import_bundle
from .security import COOKIE, ApiError, current_session, json_body, require_csrf, require_session

router = APIRouter(prefix='/api')
SORTS = ['runs', 'wickets', 'strike_rate', 'average', 'economy', 'name']


class InvalidFilter(ValueError):
    pass


def team_filter(team: str = ''):
    try:
        return int(team) if team else None
    except ValueError:
        raise InvalidFilter()


def reader(request: Request):
    with request.app.state.engine.connect() as db:
        yield db


@router.get('/session')
def get_session(request: Request):
    s = current_session(request)
    return {'authenticated': bool(s), 'csrf': s['csrf'] if s else None}


@router.get('/summary', dependencies=[Depends(require_session)])
def summary(team=Depends(team_filter), db=Depends(reader)):
    return analytics.summary(db, team)


@router.get('/teams', dependencies=[Depends(require_session)])
def teams(db=Depends(reader)):
    return analytics.teams(db)


@router.get('/matches', dependencies=[Depends(require_session)])
def matches(team=Depends(team_filter), db=Depends(reader)):
    return analytics.match_list(db, team)


@router.get('/matches/{match_id}', dependencies=[Depends(require_session)])
def match(match_id: str, db=Depends(reader)):
    m = analytics.match_detail(db, match_id)
    if not m:
        raise ApiError(404, 'Match not found')
    return m


@router.get('/players', dependencies=[Depends(require_session)])
def players(q: str = '', min: str = '0', sort: str = 'runs', team=Depends(team_filter), db=Depends(reader)):
    try:
        minimum = int(min)
    except ValueError:
        raise InvalidFilter()
    if sort not in SORTS:
        raise InvalidFilter()
    ps = [p for p in analytics.players(db, team) if q.lower() in p['name'].lower() and p['innings'] >= minimum]
    ps.sort(key=lambda p: ((p[sort] is None, p[sort] if sort in ['name', 'economy'] else -(p[sort] or 0)), p['name']))
    return ps


@router.get('/players/{player_id}', dependencies=[Depends(require_session)])
def player(player_id: str, team=Depends(team_filter), db=Depends(reader)):
    p = analytics.profile(db, player_id, team)
    if not p:
        raise ApiError(404, 'Player not found')
    return p


@router.get('/rosters', dependencies=[Depends(require_session)])
def rosters(q: str = '', team=Depends(team_filter), db=Depends(reader)):
    sql = 'SELECT r.*,t.name team_name FROM roster_entries r JOIN teams t ON t.id=r.team_id WHERE lower(r.name) LIKE :q'
    args = {'q': '%' + q.lower() + '%'}
    if team:
        sql += ' AND team_id=:team'
        args['team'] = team
    return analytics.records(db, sql + ' ORDER BY t.name COLLATE "C",r.name COLLATE "C"', args)


@router.get('/notes', dependencies=[Depends(require_session)])
def get_notes(team=Depends(team_filter), db=Depends(reader)):
    if not team:
        raise InvalidFilter()
    n = db.execute(text('SELECT body,updated_at FROM notes WHERE team_id=:t'), {'t': team}).mappings().first()
    return dict(n) if n else {'body': '', 'updated_at': None}


@router.get('/data', dependencies=[Depends(require_session)])
def data(db=Depends(reader)):
    return {'imports': analytics.records(db, 'SELECT id,imported_at,matches,source FROM import_log ORDER BY id DESC LIMIT 20'),
            'warnings': analytics.records(db, "SELECT id,warning,source_url FROM matches WHERE warning<>''"),
            'coverage': analytics.summary(db)['coverage']}


@router.post('/login')
def login(request: Request, body=Depends(json_body)):
    s, error = pin.login(request.app.state.engine, body.get('pin'), request.client.host if request.client else '')
    if error:
        raise ApiError(429 if error.startswith('Too many') else 401, error)
    response = JSONResponse({'csrf': s['csrf']})
    response.set_cookie(COOKIE, s['token'], max_age=pin.SESSION_HOURS * 3600, path='/', httponly=True, samesite='strict',
                        secure=request.app.state.secure_cookies)
    return response


@router.post('/logout')
def logout(request: Request, body=Depends(json_body), s=Depends(require_csrf)):
    with request.app.state.engine.begin() as db:
        pin.logout(db, s['token_hash'])
    response = JSONResponse({'ok': True})
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict', secure=request.app.state.secure_cookies)
    return response


@router.post('/notes')
def save_notes(request: Request, body=Depends(json_body), s=Depends(require_csrf)):
    team, note = int(body['team']), body['body']
    if not isinstance(note, str) or len(note) > 10000:
        raise ValueError('Notes must be at most 10000 characters')
    with request.app.state.engine.begin() as db:
        if not db.execute(text('SELECT 1 FROM teams WHERE id=:t'), {'t': team}).first():
            raise ValueError('Unknown team')
        db.execute(text('INSERT INTO notes VALUES (:t,:b,:u) ON CONFLICT (team_id) '
                        'DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at'),
                   {'t': team, 'b': note, 'u': datetime.now(timezone.utc)})
    return {'ok': True}


@router.post('/coach')
def coach(body=Depends(json_body), s=Depends(require_csrf), db=Depends(reader)):
    question = body.get('question', '')
    if not isinstance(question, str) or len(question) > 1000:
        raise ValueError('Question must be at most 1000 characters')
    return {'answer': analytics.coach(db, str(body.get('player_id', '')), question),
            'mode': 'Evidence-based rules; no LLM connected'}


@router.post('/import')
def import_scorecards(request: Request, body=Depends(json_body), s=Depends(require_csrf)):
    with request.app.state.engine.begin() as db:
        return {'imported': import_bundle(db, body, 'User-supplied scorecard JSON')}
