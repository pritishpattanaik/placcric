"""Explicit administration commands. Nothing here runs automatically at server start.

Usage: python3 -m app.cli <command> [options]
  db-upgrade              apply Alembic migrations up to the latest revision
  db-downgrade REVISION   roll the schema back (e.g. `base`); destroys data in dropped tables
  db-status               show the current and latest schema revisions
  seed                    idempotently load bundled club listings and the bundled scorecard snapshot
  migrate-sqlite PATH     one-time copy of a legacy SQLite database (use --dry-run first)
  set-pin                 set the interim PIN (removed in Milestone 2)
"""
import argparse
import getpass
import json
import os
import sys

from alembic import command

from .config import ConfigError, get_settings, redact_url
from .db import alembic_config, make_engine, schema_status


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python3 -m app.cli', description='PlacCric administration commands')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('db-upgrade', help='apply migrations up to the latest revision')
    down = sub.add_parser('db-downgrade', help='roll back to a revision (e.g. base); data in dropped tables is lost')
    down.add_argument('revision')
    down.add_argument('--yes', action='store_true', help='confirm a destructive downgrade')
    sub.add_parser('db-status', help='show schema revision')
    sub.add_parser('seed', help='load bundled data idempotently')
    mig = sub.add_parser('migrate-sqlite', help='copy a legacy SQLite database into PostgreSQL')
    mig.add_argument('sqlite_path')
    mig.add_argument('--dry-run', action='store_true', help='verify the full copy, then roll back')
    sub.add_parser('set-pin', help='set the interim workspace PIN (revokes sessions)')
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ConfigError as e:
        sys.exit(str(e))
    url = settings.database_url
    engine = make_engine(url)
    print(f'Database: {redact_url(url)}', file=sys.stderr)
    try:
        if args.command == 'db-upgrade':
            command.upgrade(alembic_config(url), 'head')
            print('Schema is at revision', schema_status(engine, url)[0])
        elif args.command == 'db-downgrade':
            if not args.yes:
                sys.exit('Downgrading drops tables and their data. Back up first (see README), then re-run with --yes.')
            command.downgrade(alembic_config(url), args.revision)
            print('Schema is at revision', schema_status(engine, url)[0] or 'base (empty)')
        elif args.command == 'db-status':
            current, head, ok = schema_status(engine, url)
            print(f'current={current or "none"} latest={head} ' + ('up to date' if ok else 'MIGRATION REQUIRED'))
            return 0 if ok else 1
        else:
            current, head, ok = schema_status(engine, url)
            if not ok:
                sys.exit(f'Schema is at {current or "no revision"}, expected {head}. Run `python3 -m app.cli db-upgrade`.')
            if args.command == 'seed':
                from .ingestion.scorecards import seed
                with engine.begin() as db:
                    print(json.dumps(seed(db), indent=2))
            elif args.command == 'migrate-sqlite':
                from .sqlite_migration import MigrationError, migrate
                try:
                    report = migrate(args.sqlite_path, engine, url, dry_run=args.dry_run)
                except MigrationError as e:
                    sys.exit(f'Migration aborted: {e}')
                print(json.dumps(report, indent=2))
                print('DRY RUN: verified, then rolled back. Nothing was written.' if args.dry_run
                      else 'Migration committed and verified. The SQLite file was not modified.', file=sys.stderr)
            elif args.command == 'set-pin':
                from .auth import pin
                value = os.environ.get('PLACCRIC_PIN') or prompt_pin()
                try:
                    with engine.begin() as db:
                        pin.set_pin(db, value)
                except ValueError as e:
                    sys.exit(str(e))
                print('PIN updated. Existing sessions ended.')
    finally:
        engine.dispose()
    return 0


def prompt_pin():
    value = getpass.getpass('Create your PlacCric PIN (6–12 digits): ')
    if value != getpass.getpass('Confirm PIN: '):
        sys.exit('PINs did not match; run again.')
    return value


if __name__ == '__main__':
    sys.exit(main())
