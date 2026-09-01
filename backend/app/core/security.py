"""Password hashing and token minting.

Small, boring, and deliberately free of policy: everything here either succeeds or
returns None. Who may do what is decided in `app.api.deps`, against a user this module
has already proven is who they say they are.

Two choices worth stating:

  * Argon2id, not bcrypt or a bare SHA. Legal Metrology accounts belong to enforcement
    officers, and a leaked table of fast hashes is a leaked set of enforcement
    identities.
  * `verify_password` runs the hasher even when the account does not exist. Returning
    early on an unknown email makes the response measurably faster for wrong emails
    than for wrong passwords, which turns the login endpoint into a way to enumerate
    which officers have accounts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

log = logging.getLogger(__name__)

_hasher = PasswordHasher()

TokenKind = Literal["access", "refresh"]

# The value shipped in config.py. `app.main` refuses to start outside development while
# this is still in use — it is in the repository, so anyone with the source could mint
# an administrator token.
DEFAULT_DEV_SECRET = "dev-only-secret-change-me"

# A hash of a value nobody can supply, used to spend the same time on a missing account
# as on a wrong password. Computed once at import.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")

# The shortest password worth calling one. Length carries far more entropy than a
# character-class rule, which mostly produces "Password1!" and a reused secret.
MIN_PASSWORD_LENGTH = 12


class WeakPassword(ValueError):
    """The password is too short to protect an enforcement account."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"A password must be at least {MIN_PASSWORD_LENGTH} characters. "
            "A memorable phrase of several words is both stronger and easier to type "
            "on a phone in a market."
        )
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password in constant-ish time whether or not the account exists."""
    candidate = password_hash or _DUMMY_HASH
    try:
        _hasher.verify(candidate, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash predates the current Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# ----------------------------------------------------------------------------- tokens


def _expiry(kind: TokenKind) -> datetime:
    now = datetime.now(UTC)
    if kind == "access":
        return now + timedelta(minutes=settings.access_token_ttl_minutes)
    return now + timedelta(days=settings.refresh_token_ttl_days)


def create_token(subject: str, kind: TokenKind, *, role: str | None = None) -> str:
    """Mint a signed token for one user.

    `kind` is inside the signed payload rather than implied by where the token turns
    up. Without it a refresh token — which is long-lived by design — would be accepted
    anywhere an access token is, and a stolen one would stay useful for a fortnight.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "kind": kind,
        "iat": now,
        "exp": _expiry(kind),
        "jti": uuid.uuid4().hex,
    }
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expect: TokenKind) -> dict[str, Any] | None:
    """Verify a token and confirm it is the kind being asked for.

    Returns None for anything wrong — expired, tampered, wrong kind, wrong algorithm.
    The caller turns that into a 401; distinguishing the reasons for the client would
    only tell an attacker which part of their forgery to fix.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "kind"]},
        )
    except jwt.PyJWTError:
        return None

    if payload.get("kind") != expect:
        return None
    return payload
