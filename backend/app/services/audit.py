"""The append-only record of what officers did.

Every automated finding in this system is decision support, which means the decisions
that matter are the human ones: confirming a violation, overriding a machine verdict,
opening a case. Those are the acts a manufacturer may later contest, so they are written
down with who, when, and what the value was before.

Nothing here ever updates or deletes a row. An audit log that can be edited is a log of
what someone was willing to admit to.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models.tables import AuditLog, User

log = logging.getLogger(__name__)


class Action:
    """The verbs worth recording. Strings, so a new one needs no migration."""

    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    USER_CREATED = "USER_CREATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    SCAN_FILED = "SCAN_FILED"
    IMAGE_ADDED = "IMAGE_ADDED"
    IMAGE_REMOVED = "IMAGE_REMOVED"
    IMAGE_REPLACED = "IMAGE_REPLACED"
    RETENTION_DECISION = "RETENTION_DECISION"
    SCAN_DELETED = "SCAN_DELETED"
    RETENTION_WINDOW_CHANGED = "RETENTION_WINDOW_CHANGED"
    FINDING_OVERRIDDEN = "FINDING_OVERRIDDEN"
    OVERRIDE_WITHDRAWN = "OVERRIDE_WITHDRAWN"


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    actor: User | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one entry. The caller commits, so the act and its record share a
    transaction — an override that succeeded while its audit entry was rolled back
    would be exactly the change nobody can account for."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        at=utcnow(),
    )
    db.add(entry)
    return entry


def history(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    """Most recent first."""
    statement = select(AuditLog)
    if entity_type is not None:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    statement = statement.order_by(AuditLog.at.desc()).limit(limit)
    return list(db.execute(statement).scalars().all())
