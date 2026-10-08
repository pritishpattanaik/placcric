"""Runtime configuration from environment variables (optionally a local .env file)."""
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ('development', 'production', 'test')


class ConfigError(RuntimeError):
    """Raised for missing or invalid configuration. Messages never include secrets."""


def load_env_file(path=ROOT / '.env'):
    """Load KEY=VALUE lines from a local .env file without overriding real environment variables."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        os.environ.setdefault(key, value)


def normalise_database_url(url, variable='DATABASE_URL'):
    """Accept postgresql:// URLs and select the psycopg 3 driver. Reject anything that is not PostgreSQL."""
    if not url:
        raise ConfigError(f'{variable} is not set. Copy .env.example to .env and set a PostgreSQL URL.')
    scheme = urlsplit(url).scheme
    if scheme in ('postgresql', 'postgres'):
        return 'postgresql+psycopg://' + url.split('://', 1)[1]
    if scheme == 'postgresql+psycopg':
        return url
    raise ConfigError(f'{variable} must be a postgresql:// URL (got scheme "{scheme}").')


def redact_url(url):
    """Return a URL safe for logs: the password is never shown."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.replace(':' + parts.password + '@', ':***@', 1)
    return parts._replace(netloc=netloc).geturl()


@dataclass(frozen=True)
class Settings:
    database_url: str
    environment: str = 'development'


def get_settings():
    load_env_file()
    environment = os.environ.get('PLACCRIC_ENV', 'development')
    if environment not in ENVIRONMENTS:
        raise ConfigError(f'PLACCRIC_ENV must be one of {", ".join(ENVIRONMENTS)}.')
    return Settings(database_url=normalise_database_url(os.environ.get('DATABASE_URL')), environment=environment)
