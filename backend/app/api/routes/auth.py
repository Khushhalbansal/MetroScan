"""Signing in, and managing who may."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import (
    GRANTABLE_ROLES,
    AdminOnly,
    AnyOfficer,
    CurrentUser,
    DbSession,
    WritableDb,
    _unauthorised,
)
from app.core.config import settings
from app.core.security import (
    WeakPassword,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.tables import User
from app.schemas.auth import (
    AuditEntryOut,
    CreateUserRequest,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserOut,
)
from app.services import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every way a sign-in can fail. Saying "no such account" tells an
# attacker which officers exist; saying "wrong password" confirms it outright.
BAD_CREDENTIALS = "That email and password do not match an active account."


def _tokens(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_token(user.id, "access", role=user.role.value),
        refresh_token=create_token(user.id, "refresh"),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenPair, summary="Sign in")
def login(body: LoginRequest, db: WritableDb) -> TokenPair:
    """Exchange an email and password for an access and refresh token.

    Writes to the audit log on both success and failure, which is why it needs a
    writable database: a run of failed sign-ins against one officer's account is
    something an administrator needs to be able to see afterwards.
    """
    user = db.execute(select(User).where(User.email == body.email)).scalars().first()

    # Runs the hasher even when the account does not exist, so a wrong email and a
    # wrong password take the same time and neither can be told apart by a stopwatch.
    if not verify_password(body.password, user.password_hash if user else None):
        audit.record(
            db,
            action=audit.Action.LOGIN_FAILED,
            entity_type="user",
            entity_id=user.id if user else "unknown",
            actor=user,
            after={"email": body.email},
        )
        db.commit()
        raise _unauthorised(BAD_CREDENTIALS)

    assert user is not None  # verify_password returns False when the account is absent
    if not user.is_active:
        # Deliberately the same message as a wrong password: whether an account is
        # merely disabled is not something an unauthenticated caller should learn.
        audit.record(
            db,
            action=audit.Action.LOGIN_FAILED,
            entity_type="user",
            entity_id=user.id,
            actor=user,
            after={"email": body.email, "reason": "inactive"},
        )
        db.commit()
        raise _unauthorised(BAD_CREDENTIALS)

    audit.record(
        db, action=audit.Action.LOGIN, entity_type="user", entity_id=user.id, actor=user
    )
    db.commit()
    return _tokens(user)


@router.post("/refresh", response_model=TokenPair, summary="Renew an expired sign-in")
def refresh(body: RefreshRequest, db: DbSession) -> TokenPair:
    payload = decode_token(body.refresh_token, expect="refresh")
    if payload is None:
        raise _unauthorised("That session has expired. Sign in again.")

    user = db.execute(select(User).where(User.id == payload["sub"])).scalars().first()
    if user is None or not user.is_active:
        raise _unauthorised("That session is no longer valid. Sign in again.")
    return _tokens(user)


@router.get("/me", response_model=UserOut, summary="The signed-in officer")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


# ------------------------------------------------------------------ administration


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
def create_user(body: CreateUserRequest, db: WritableDb, admin: AdminOnly) -> UserOut:
    if body.role not in GRANTABLE_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{body.role.value} is not a role this deployment grants; "
            f"expected one of {', '.join(r.value for r in GRANTABLE_ROLES)}.",
        )
    if db.execute(select(User).where(User.email == body.email)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email exists.")

    try:
        password_hash = hash_password(body.password)
    except WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=password_hash,
        role=body.role,
        jurisdiction=body.jurisdiction,
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action=audit.Action.USER_CREATED,
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        after={"email": user.email, "role": user.role.value},
    )
    db.commit()
    return UserOut.model_validate(user, from_attributes=True)


@router.get("/users", response_model=list[UserOut], summary="Every account")
def list_users(db: DbSession, admin: AdminOnly) -> list[UserOut]:
    rows = db.execute(select(User).order_by(User.email)).scalars().all()
    return [UserOut.model_validate(u, from_attributes=True) for u in rows]


@router.post("/users/{user_id}:deactivate", response_model=UserOut, summary="Disable an account")
def deactivate_user(user_id: str, db: WritableDb, admin: AdminOnly) -> UserOut:
    user = db.execute(select(User).where(User.id == user_id)).scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")
    if user.id == admin.id:
        # Not paternalism: an administrator who locks out the last administrator leaves
        # a deployment with no way to grant the role back short of editing the database.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An administrator cannot deactivate their own account. Ask another "
            "administrator to do it.",
        )

    before = {"is_active": user.is_active}
    user.is_active = False
    audit.record(
        db,
        action=audit.Action.USER_DEACTIVATED,
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        before=before,
        after={"is_active": False},
    )
    db.commit()
    return UserOut.model_validate(user, from_attributes=True)


# ------------------------------------------------------------------------- the log


@router.get("/audit", response_model=list[AuditEntryOut], summary="The audit trail")
def read_audit(
    db: DbSession,
    officer: AnyOfficer,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    actor_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEntryOut]:
    """Readable by any officer, not just administrators.

    An audit trail only an administrator can read cannot be used to check an
    administrator.
    """
    entries = audit.history(
        db, entity_type=entity_type, entity_id=entity_id, actor_id=actor_id, limit=limit
    )
    return [
        AuditEntryOut(
            id=e.id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            actor_id=e.actor_id,
            actor_email=e.actor.email if e.actor else None,
            at=e.at,
            before=e.before,
            after=e.after,
        )
        for e in entries
    ]
