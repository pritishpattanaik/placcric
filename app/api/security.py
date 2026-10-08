"""Request guards shared by API routes: JSON body limits, origin checks, sessions and CSRF."""
import hmac
import json

from fastapi import HTTPException, Request

from ..auth import pin

MAX_BODY = 2_000_000
COOKIE = 'placcric_session'


class ApiError(HTTPException):
    """An error rendered as {"error": message}."""


async def json_body(request: Request):
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
    origin = request.headers.get('origin')
    if origin and origin != expected:
        raise ApiError(403, 'Invalid origin')
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        raise ApiError(415, 'JSON required')
    try:
        size = int(request.headers.get('content-length', '0'))
    except ValueError:
        size = 0
    if not 0 < size <= MAX_BODY:
        raise ApiError(413, 'Upload must be at most 2 MB')
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ApiError(413, 'Upload must be at most 2 MB')
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiError(400, 'Invalid JSON')
    if not isinstance(data, dict):
        raise ApiError(400, 'JSON object required')
    return data


def current_session(request: Request):
    with request.app.state.engine.connect() as db:
        return pin.session(db, request.cookies.get(COOKIE, ''))


def require_session(request: Request):
    s = current_session(request)
    if not s:
        raise ApiError(401, 'Please sign in')
    return s


def require_csrf(request: Request):
    s = require_session(request)
    if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), s['csrf']):
        raise ApiError(403, 'Invalid session verification')
    return s
