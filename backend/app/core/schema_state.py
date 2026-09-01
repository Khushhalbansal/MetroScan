"""Is the database actually at the schema this code expects?

A server whose database is behind its migrations does not fail at boot. It starts
cleanly, serves reads, and then throws OperationalError on the first INSERT that
touches a column the database does not have — so the failure surfaces as a 500 on an
officer's upload, after the scan has already been run, with the photographs discarded.

Knowing the answer lets the API say "this server is not ready" instead, which is a
different and much more useful thing to be told.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import REPO_ROOT

log = logging.getLogger(__name__)

BACKEND = REPO_ROOT / "backend"
UPGRADE_COMMAND = "alembic upgrade head"


class SchemaState(StrEnum):
    CURRENT = "CURRENT"
    # The database exists but predates the code — writes will fail on missing columns.
    BEHIND = "BEHIND"
    # No alembic_version table: this database has never been migrated.
    UNINITIALISED = "UNINITIALISED"
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True)
class SchemaReport:
    state: SchemaState
    current: str | None
    head: str | None
    message: str

    @property
    def writable(self) -> bool:
        return self.state is SchemaState.CURRENT


def head_revision() -> str | None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


@contextmanager
def _connection(bind: Engine | Connection):
    """A connection from either an engine or an already-open connection.

    A Session's bind is whichever the caller configured, and opening a second
    connection to a SQLite file while the session holds one is a way to meet the
    database locked. So an existing connection is reused and left open for its owner.
    """
    if isinstance(bind, Connection):
        yield bind
        return
    with bind.connect() as connection:
        yield connection


def inspect_schema(bind: Engine | Connection) -> SchemaReport:
    """Compare the database's applied revision against the code's head revision."""
    head = head_revision()
    try:
        with _connection(bind) as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    except SQLAlchemyError as exc:
        return SchemaReport(
            state=SchemaState.UNREACHABLE,
            current=None,
            head=head,
            message=f"The database could not be reached: {exc.__class__.__name__}.",
        )

    if current is None:
        return SchemaReport(
            state=SchemaState.UNINITIALISED,
            current=None,
            head=head,
            message=(
                "This database has no schema yet. Create it with "
                f"`{UPGRADE_COMMAND}` before filing scans."
            ),
        )
    if current != head:
        return SchemaReport(
            state=SchemaState.BEHIND,
            current=current,
            head=head,
            message=(
                f"The database is at revision {current} but this code expects {head}. "
                f"Run `{UPGRADE_COMMAND}`. Filing scans is refused until then, because "
                "a scan written against the wrong schema is a lost inspection."
            ),
        )
    return SchemaReport(
        state=SchemaState.CURRENT,
        current=current,
        head=head,
        message="The database schema is up to date.",
    )
