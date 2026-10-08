"""Database engine helpers and Alembic schema-version checks."""
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from .config import ROOT


def make_engine(database_url, **kwargs):
    return create_engine(database_url, pool_pre_ping=True, future=True, **kwargs)


def alembic_config(database_url):
    cfg = Config(str(ROOT / 'alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'migrations'))
    # Passed via attributes rather than the ini file so that '%' in passwords is not interpolated.
    cfg.attributes['database_url'] = database_url
    return cfg


def head_revision(database_url):
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def current_revision(engine):
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def schema_status(engine, database_url):
    """Return (current, head, is_current)."""
    current, head = current_revision(engine), head_revision(database_url)
    return current, head, current == head
