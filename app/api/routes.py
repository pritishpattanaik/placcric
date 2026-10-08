"""JSON API. Every route except /api/session and /api/login requires a session; POSTs also require CSRF."""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import analytics
from ..auth import pin
from ..ingestion import staging
from .security import COOKIE, ApiError, current_session, json_body, require_admin, require_csrf, require_session, upload_body

router = APIRouter(prefix='/api')
SORTS = ['runs', 'wickets', 'strike_rate', 'average', 'economy', 'name']


class InvalidFilter(ValueError):
    pass


def team_filter(team: str = ''):
    try:
        return int(team) if team else None
    except ValueError:
        raise InvalidFilter()


def tournament_filter(tournament: str = ''):
    try:
        return int(tournament) if tournament else None
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
def summary(team=Depends(team_filter), tournament=Depends(tournament_filter), db=Depends(reader)):
    return analytics.summary(db, team, tournament)


@router.get('/teams', dependencies=[Depends(require_session)])
def teams(tournament=Depends(tournament_filter), db=Depends(reader)):
    return analytics.teams(db, tournament)


@router.get('/matches', dependencies=[Depends(require_session)])
def matches(team=Depends(team_filter), tournament=Depends(tournament_filter), db=Depends(reader)):
    return analytics.match_list(db, team, tournament)


@router.get('/matches/{match_id}', dependencies=[Depends(require_session)])
def match(match_id: str, db=Depends(reader)):
    m = analytics.match_detail(db, match_id)
    if not m:
        raise ApiError(404, 'Match not found')
    return m


@router.get('/players', dependencies=[Depends(require_session)])
def players(q: str = '', min: str = '0', sort: str = 'runs', team=Depends(team_filter),
            tournament=Depends(tournament_filter), db=Depends(reader)):
    try:
        minimum = int(min)
    except ValueError:
        raise InvalidFilter()
    if sort not in SORTS:
        raise InvalidFilter()
    ps = [p for p in analytics.players(db, team, tournament) if q.lower() in p['name'].lower() and p['innings'] >= minimum]
    ps.sort(key=lambda p: ((p[sort] is None, p[sort] if sort in ['name', 'economy'] else -(p[sort] or 0)), p['name']))
    return ps


@router.get('/players/{player_id}', dependencies=[Depends(require_session)])
def player(player_id: str, team=Depends(team_filter), tournament=Depends(tournament_filter), db=Depends(reader)):
    p = analytics.profile(db, player_id, team, tournament)
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
            'coverage': analytics.coverage(db)}


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


@router.get('/tournaments', dependencies=[Depends(require_session)])
def tournaments(db=Depends(reader)):
    return analytics.tournaments(db)


@router.post('/tournaments')
def create_tournament(request: Request, body=Depends(json_body), s=Depends(require_admin)):
    name = body.get('name')
    if not isinstance(name, str) or not 3 <= len(name.strip()) <= 200:
        raise ValueError('Tournament name must be 3–200 characters')
    external_id = str(body.get('external_id') or '').strip()
    if external_id and not external_id.isdigit():
        raise ValueError('CricHeroes tournament ID must be a number (from the tournament link)')
    slug = str(body.get('slug') or '').strip()
    if slug and not re.fullmatch(r'[a-z0-9-]{1,200}', slug):
        raise ValueError('Slug must be the lower-case words-with-dashes part of the tournament link')
    overs_, spell = body.get('overs_per_innings'), body.get('max_overs_per_bowler')
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (overs_, spell)) or not 1 <= spell <= overs_ <= 50:
        raise ValueError('Overs per innings (1–50) and maximum overs per bowler (1–overs) are required')
    with request.app.state.engine.begin() as db:
        if db.execute(text('SELECT 1 FROM tournaments WHERE lower(name)=lower(:n) OR (:e <> \'\' AND external_id=:e)'),
                      {'n': name.strip(), 'e': external_id}).first():
            raise ValueError('A tournament with that name or CricHeroes ID already exists')
        tid = db.execute(text('INSERT INTO tournaments(provider, external_id, name, slug, overs_per_innings, '
                              "max_overs_per_bowler) VALUES ('cricheroes', :e, :n, :s, :o, :m) RETURNING id"),
                         {'e': external_id or None, 'n': name.strip(), 's': slug, 'o': overs_, 'm': spell}).scalar_one()
    return {'id': tid}


def _staging_errors(fn, *args):
    try:
        return fn(*args)
    except staging.ImportError_ as e:
        raise ApiError(400, str(e))
    except LookupError as e:
        raise ApiError(404, str(e))


@router.post('/imports')
def upload_import(request: Request, tournament: int, match_id: str = '', source_url: str = '',
                  s=Depends(require_admin), upload=Depends(upload_body)):
    kind, data, filename = upload
    batch_id, existing = _staging_errors(staging.create_batch, request.app.state.engine, request.app.state.upload_dir,
                                         data, filename, kind, tournament, match_id, source_url)
    return {'batch_id': batch_id, 'already_uploaded': existing}


@router.get('/imports', dependencies=[Depends(require_session)])
def list_imports(db=Depends(reader)):
    return staging.list_batches(db)


@router.get('/imports/{batch_id}', dependencies=[Depends(require_session)])
def import_preview(batch_id: int, db=Depends(reader)):
    return _staging_errors(staging.preview, db, batch_id)


@router.post('/imports/{batch_id}/approve')
def approve_import(request: Request, batch_id: int, body=Depends(json_body), s=Depends(require_admin)):
    return {'outcome': _staging_errors(staging.approve, request.app.state.engine, batch_id, body.get('decisions'))}


@router.post('/imports/{batch_id}/reject')
def reject_import(request: Request, batch_id: int, body=Depends(json_body), s=Depends(require_admin)):
    _staging_errors(staging.reject, request.app.state.engine, batch_id)
    return {'ok': True}


@router.get('/matches/{match_id}/revisions', dependencies=[Depends(require_session)])
def match_revisions(match_id: str, db=Depends(reader)):
    return staging.revisions(db, match_id)


@router.post('/matches/{match_id}/restore')
def restore_revision(request: Request, match_id: str, body=Depends(json_body), s=Depends(require_admin)):
    number = body.get('revision')
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError('Revision number required')
    revision = _staging_errors(staging.restore, request.app.state.engine, match_id, number)
    return {'revision': revision, 'unchanged': revision is None}
