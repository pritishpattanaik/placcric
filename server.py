#!/usr/bin/env python3
"""PlacCric server: python3 server.py --port 8000

Configuration comes from environment variables (see .env.example). By default it binds to
127.0.0.1 only. It never migrates, seeds or resets the database; run
`python3 -m app.cli db-upgrade` and `python3 -m app.cli seed` explicitly.
"""
import argparse
import os
import sys

try:
    import uvicorn
    from sqlalchemy.exc import OperationalError
except ImportError:
    sys.exit('Dependencies are missing. Activate your virtual environment and run: pip install -r requirements.txt')

from app.cli import prompt_pin
from app.config import ConfigError, get_settings, redact_url
from app.db import make_engine, schema_status
from app.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, help='listen port (default: PLACCRIC_PORT or 8000)')
    parser.add_argument('--reset-pin', action='store_true', help='set a new interim PIN and revoke sessions')
    args = parser.parse_args()
    try:
        settings = get_settings(port=args.port)
    except ConfigError as e:
        sys.exit(str(e))
    engine = make_engine(settings.database_url)
    try:
        current, head, ok = schema_status(engine, settings.database_url)
    except OperationalError:
        sys.exit(f'Cannot connect to PostgreSQL at {redact_url(settings.database_url)}. '
                 'Is PostgreSQL running and is DATABASE_URL correct? See README.')
    if not ok:
        sys.exit(f'Database schema is at {current or "no revision"}, expected {head}. Run: python3 -m app.cli db-upgrade')

    from app.auth import pin
    with engine.connect() as db:
        need_pin = args.reset_pin or not pin.configured(db)
    if need_pin:
        value = os.environ.get('PLACCRIC_PIN')
        if not value and not sys.stdin.isatty():
            sys.exit('No PIN is configured. Set one interactively first: python3 -m app.cli set-pin '
                     '(with Docker: docker compose run --rm app python -m app.cli set-pin)')
        value = value or prompt_pin()
        try:
            with engine.begin() as db:
                pin.set_pin(db, value)
        except ValueError as e:
            sys.exit(str(e))
        if args.reset_pin:
            print('PIN updated. Existing sessions ended.')
            return

    app = create_app(engine, settings.allowed_hosts, settings.database_url, secure_cookies=settings.cookie_secure)
    print(f'PlacCric listening on {settings.host}:{settings.port} ({settings.environment}); '
          f'allowed hosts: {", ".join(settings.allowed_hosts)}', flush=True)
    proxy = {'proxy_headers': True, 'forwarded_allow_ips': settings.forwarded_allow_ips} if settings.forwarded_allow_ips \
        else {'proxy_headers': False}
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level='warning', server_header=False, **proxy)
    except OSError:
        sys.exit(f'Port {settings.port} is already in use. Stop the other server with Ctrl+C, then run again.')
    print('\nPlacCric stopped.')


if __name__ == '__main__':
    main()
