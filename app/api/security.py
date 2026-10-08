"""Request guards shared by API routes: JSON body limits, origin checks, sessions and CSRF."""
import hmac
import json
from urllib.parse import unquote

from fastapi import HTTPException, Request

from ..auth import pin

MAX_BODY = 2_000_000
MAX_UPLOAD = {'application/pdf': ('pdf', 10_000_000), 'application/json': ('json', 2_000_000)}
COOKIE = 'placcric_session'


class ApiError(HTTPException):
    """An error rendered as {"error": message}."""


def check_origin(request: Request):
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
    origin = request.headers.get('origin')
    if origin and origin != expected:
        raise ApiError(403, 'Invalid origin')


async def json_body(request: Request):
    check_origin(request)
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


async def upload_body(request: Request):
    """Raw file upload: (kind, bytes, display filename). The filename is from X-Filename (URL-encoded)."""
    check_origin(request)
    content_type = request.headers.get('content-type', '').split(';')[0].strip()
    if content_type not in MAX_UPLOAD:
        raise ApiError(415, 'Upload a PDF or JSON file')
    kind, limit = MAX_UPLOAD[content_type]
    try:
        size = int(request.headers.get('content-length', '0'))
    except ValueError:
        size = 0
    if not 0 < size <= limit:
        raise ApiError(413, f'{kind.upper()} uploads must be at most {limit // 1_000_000} MB')
    raw = await request.body()
    if len(raw) > limit:
        raise ApiError(413, f'{kind.upper()} uploads must be at most {limit // 1_000_000} MB')
    return kind, raw, unquote(request.headers.get('x-filename', ''))[:300]


def require_admin(request: Request):
    """Admin-only actions (imports, approvals, restores). Until Milestone 2 adds roles, the single
    PIN workspace user is the admin; this dependency is where the role check will go."""
    return require_csrf(request)
