"""Interim single-user PIN authentication, ported unchanged in behaviour from the SQLite MVP.

Scheduled for removal in Milestone 2 (Google OpenID Connect). PINs are salted PBKDF2-SHA256
hashes; session tokens are random and stored only as SHA-256 digests.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

ITERATIONS = 600000
SESSION_HOURS = 12
THROTTLE_WINDOW = timedelta(minutes=15)
MAX_ATTEMPTS = 8


def utcnow():
    return datetime.now(timezone.utc)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def configured(db):
    return db.execute(text('SELECT 1 FROM pin_credentials WHERE id = 1')).first() is not None


def set_pin(db, pin):
    """Call inside a transaction. Replaces the PIN and revokes every session."""
    if not isinstance(pin, str) or not re.fullmatch(r'\d{6,12}', pin):
        raise ValueError('Choose a PIN of 6–12 digits')
    salt = secrets.token_hex(16)
    db.execute(text('INSERT INTO pin_credentials VALUES (1, :s, :h) '
                    'ON CONFLICT (id) DO UPDATE SET salt = excluded.salt, pin_hash = excluded.pin_hash'),
               {'s': salt, 'h': hash_pin(pin, salt)})
    db.execute(text('DELETE FROM auth_sessions'))


def login(engine, pin, ip):
    """Return (session, error). Each attempt is recorded before the PIN is checked."""
    stamp = utcnow()
    with engine.begin() as db:
        db.execute(text('DELETE FROM login_attempts WHERE attempted_at < :t'), {'t': stamp - THROTTLE_WINDOW})
        db.execute(text('DELETE FROM auth_sessions WHERE expires_at < :t'), {'t': stamp})
        if db.execute(text('SELECT count(*) FROM login_attempts WHERE ip = :ip'), {'ip': ip}).scalar_one() >= MAX_ATTEMPTS:
            return None, 'Too many attempts. Try again in 15 minutes.'
        db.execute(text('INSERT INTO login_attempts(ip, attempted_at) VALUES (:ip, :t)'), {'ip': ip, 't': stamp})
    with engine.connect() as db:
        row = db.execute(text('SELECT salt, pin_hash FROM pin_credentials WHERE id = 1')).mappings().first()
    if not row:
        return None, 'PIN has not been configured in Terminal.'
    if not isinstance(pin, str) or not re.fullmatch(r'\d{6,12}', pin):
        return None, 'Incorrect PIN.'
    if not hmac.compare_digest(hash_pin(pin, row['salt']), row['pin_hash']):
        return None, 'Incorrect PIN.'
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with engine.begin() as db:
        db.execute(text('DELETE FROM login_attempts WHERE ip = :ip'), {'ip': ip})
        db.execute(text('INSERT INTO auth_sessions VALUES (:h, :c, :e)'),
                   {'h': digest(token), 'c': csrf, 'e': stamp + timedelta(hours=SESSION_HOURS)})
    return {'token': token, 'csrf': csrf}, None


def session(db, token):
    if not token:
        return None
    row = db.execute(text('SELECT token_hash, csrf, expires_at FROM auth_sessions WHERE token_hash = :h AND expires_at > :t'),
                     {'h': digest(token), 't': utcnow()}).mappings().first()
    return dict(row) if row else None


def logout(db, token_hash):
    db.execute(text('DELETE FROM auth_sessions WHERE token_hash = :h'), {'h': token_hash})
