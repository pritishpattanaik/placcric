"""FastAPI application factory. Creating the app never migrates, seeds or resets the database."""
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.routes import InvalidFilter, router
from .config import ROOT
from .db import schema_status

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
SECURITY_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                    'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': CSP}
STATIC = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css',
          '/favicon.svg': 'favicon.svg'}
MEDIA = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8',
         'svg': 'image/svg+xml'}


def error(status, message):
    return JSONResponse({'error': message}, status_code=status)


def create_app(engine, allowed_hosts, database_url=None, secure_cookies=False):
    """allowed_hosts: exact Host header values, e.g. ['localhost:8000', '127.0.0.1:8000']."""
    app = FastAPI(title='PlacCric', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.state.secure_cookies = secure_cookies
    allowed = set(allowed_hosts)

    @app.middleware('http')
    async def guard(request: Request, call_next):
        # Health probes carry no data and may come from container tooling with any Host header.
        if request.url.path not in ('/healthz', '/readyz') and request.headers.get('host', '') not in allowed:
            response = error(403, 'Invalid host')
        else:
            response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if exc.status_code == 404 and exc.detail == 'Not Found':
            return error(404, 'Unknown API route' if request.url.path.startswith('/api/') else 'Not found')
        if exc.status_code == 405:
            return error(405, 'Method not allowed')
        return error(exc.status_code, str(exc.detail))

    @app.exception_handler(InvalidFilter)
    async def invalid_filter(request, exc):
        return error(400, 'Invalid filter')

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error(400, 'Invalid filter' if request.method == 'GET' else 'Invalid request')

    @app.exception_handler(ValueError)
    @app.exception_handler(KeyError)
    @app.exception_handler(TypeError)
    async def bad_input(request, exc):
        if request.method == 'GET':
            return error(400, 'Invalid filter')
        message = str(exc)[:200] if isinstance(exc, ValueError) else f'Missing or invalid field {exc}'[:200]
        return error(400, message)

    @app.exception_handler(IntegrityError)
    async def integrity(request, exc):
        return error(400, 'The request conflicts with stored data')

    app.include_router(router)

    @app.get('/healthz')
    def healthz():
        return {'status': 'ok', 'version': os.environ.get('PLACCRIC_VERSION', 'dev')}

    @app.get('/readyz')
    def readyz():
        try:
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            if database_url:
                current, head, ok = schema_status(engine, database_url)
                if not ok:
                    return JSONResponse({'status': 'unavailable', 'database': 'ok', 'schema': 'migration required'},
                                        status_code=503)
        except SQLAlchemyError:
            return JSONResponse({'status': 'unavailable', 'database': 'unreachable'}, status_code=503)
        return {'status': 'ready', 'database': 'ok', 'schema': 'current'}

    for path, name in STATIC.items():
        def serve(name=name):
            return Response(ROOT.joinpath('web', name).read_bytes(), media_type=MEDIA[name.rsplit('.', 1)[1]])
        app.add_api_route(path, serve, methods=['GET'], include_in_schema=False)
    return app
