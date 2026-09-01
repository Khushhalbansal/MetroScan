"""Auth request and response shapes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires.")


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    jurisdiction: str | None = None
    is_active: bool
    created_at: datetime | None = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    role: Role
    jurisdiction: str | None = Field(default=None, max_length=120)


class AuditEntryOut(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    actor_id: str | None = None
    actor_email: str | None = None
    at: datetime
    before: dict | None = None
    after: dict | None = None


class OverrideRequest(BaseModel):
    """An officer's decision to overrule an automated finding.

    `reason` is mandatory and has a floor. An override is the point where a human takes
    responsibility for a verdict the machine reached differently, and "ok" recorded
    against that is not a reason — it is an unexplained change that a manufacturer's
    counsel gets to read out later.
    """

    status: str = Field(description="PASS, FAIL or NEEDS_REVIEW.")
    reason: str = Field(min_length=15, max_length=2000)
