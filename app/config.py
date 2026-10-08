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
    host: str = '127.0.0.1'
    port: int = 8000
    allowed_hosts: tuple = ()
    forwarded_allow_ips: str = ''
    cookie_secure: bool = False


def flag(name, default):
    value = os.environ.get(name, '').strip().lower()
    if not value:
        return default
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    raise ConfigError(f'{name} must be true or false.')


def get_settings(port=None):
    """Read settings from the environment. `port` (from --port) overrides PLACCRIC_PORT."""
    load_env_file()
    environment = os.environ.get('PLACCRIC_ENV', 'development')
    if environment not in ENVIRONMENTS:
        raise ConfigError(f'PLACCRIC_ENV must be one of {", ".join(ENVIRONMENTS)}.')
    try:
        port = int(port or os.environ.get('PLACCRIC_PORT') or 8000)
    except ValueError:
        raise ConfigError('PLACCRIC_PORT must be a number.')
    hosts = tuple(h.strip() for h in os.environ.get('PLACCRIC_ALLOWED_HOSTS', '').split(',') if h.strip())
    return Settings(database_url=normalise_database_url(os.environ.get('DATABASE_URL')), environment=environment,
                    host=os.environ.get('PLACCRIC_HOST', '127.0.0.1').strip() or '127.0.0.1', port=port,
                    allowed_hosts=hosts or (f'localhost:{port}', f'127.0.0.1:{port}'),
                    forwarded_allow_ips=os.environ.get('PLACCRIC_FORWARDED_ALLOW_IPS', '').strip(),
                    cookie_secure=flag('PLACCRIC_COOKIE_SECURE', environment == 'production'))
