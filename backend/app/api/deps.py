"""Shared route dependencies: the database, the schema gate, and who is asking."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.schema_state import inspect_schema
from app.core.security import decode_token
from app.models.enums import Role
from app.models.tables import User

DbSession = Annotated[Session, Depends(get_db)]

# auto_error=False so a missing header reaches our own handler and returns the same
# 401 shape as a bad one. Letting the library answer produces a 403 for "no header"
# and a 401 for "bad header", which tells an unauthenticated caller which of the two
# they got wrong.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login.")


def writable_db(db: DbSession) -> Session:
    """A session on a database whose schema matches this code.

    Guards the endpoints that write. Without it a server running behind its migrations
    accepts an upload, spends twenty seconds on OCR, and then throws OperationalError —
    the officer loses the scan and gets a 500 that says nothing about why. Refusing up
    front with 503 and the exact command to run is the same information, delivered
    before the work rather than after it.
    """
    report = inspect_schema(db.get_bind())
    if not report.writable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, report.message)
    return db


WritableDb = Annotated[Session, Depends(writable_db)]

UNAUTHENTICATED = "Sign in to continue."


def _unauthorised(detail: str = UNAUTHENTICATED) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """The authenticated officer, or 401.

    The user is loaded from the database on every request rather than trusted from the
    token's claims. A token carries the role held when it was minted; an account
    deactivated or demoted an hour ago would keep its access for the rest of the
    token's life if the claim were believed. For an enforcement system, revocation has
    to take effect when it is made.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorised()

    payload = decode_token(credentials.credentials, expect="access")
    if payload is None:
        raise _unauthorised("That sign-in has expired or is not valid. Sign in again.")

    user = db.execute(select(User).where(User.id == payload["sub"])).scalars().first()
    if user is None:
        raise _unauthorised()
    if not user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This account is not active. Ask an administrator to re-enable it.",
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*roles: Role):
    """Dependency factory gating an endpoint on the caller's role."""
    allowed = set(roles)

    def guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action needs the {' or '.join(sorted(r.value for r in allowed))} "
                f"role; this account is {user.role.value}.",
            )
        return user

    return guard


# The two roles this deployment grants. The Role enum defines more for later use, but
# only these are assignable — an unassignable role in an authorisation check is a rule
# nobody can test and everybody assumes works.
ADMIN = Role.ADMIN
OFFICER = Role.SENIOR_OFFICER
GRANTABLE_ROLES = (ADMIN, OFFICER)

AdminOnly = Annotated[User, Depends(require(ADMIN))]
AnyOfficer = Annotated[User, Depends(require(ADMIN, OFFICER))]
