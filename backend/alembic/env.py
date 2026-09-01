"""Alembic environment.

Two things are set deliberately:

  * The URL comes from `app.core.config`, never from alembic.ini. A migration that can
    be pointed at a different database than the API is reading is a way to lose an
    inspection record, and there is no reason to allow it.
  * `render_as_batch` is on. SQLite is the zero-setup default for a clean checkout and
    cannot ALTER a column in place; without batch mode every future column change would
    work in Postgres and fail on a developer's machine.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# `app.models.tables` is imported for its side effect: defining the ORM classes is what
# populates Base.metadata. Without it autogenerate compares against an empty schema and
# cheerfully writes a migration that drops every table.
import app.models.tables  # noqa: F401
from alembic import context
from app.core.config import settings
from app.core.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

# Logging is configured from alembic.ini only when this runs as the alembic CLI.
#
# `fileConfig` is destructive twice over: it disables every logger already configured in
# the process, and it replaces the root logger's handlers. A migration run in-process —
# a management command, a startup hook, a test — would therefore take the rest of the
# system's logging down with it. `app.rules.loader`'s warning that no ruleset was in
# force on a scan's date is exactly the kind of signal that must not vanish because a
# migration happened to run first: it is the only notice an officer gets that a citation
# on their report may post-date the pack.
#
# Programmatic callers set `configure_logger = False` on the Config to opt out entirely;
# `disable_existing_loggers=False` keeps the CLI path from muting the application too.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=_is_sqlite(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite(),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
