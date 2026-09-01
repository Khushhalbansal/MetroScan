"""The migrations, and whether they still describe the models.

Drift between `models/tables.py` and `alembic/versions` is silent until a deployment:
the tests pass against `create_all`, and then production runs a migration that builds a
different schema. For an inspection record that means a column an officer's finding was
written to may simply not exist on the server. The drift test below is the guard.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from alembic import command
from app.core.config import REPO_ROOT
from app.core.db import Base

# Every table the application expects to exist, named here rather than derived from the
# metadata so that a table silently dropped from the models fails this test too.
EXPECTED_TABLES = {
    "users",
    "products",
    "scans",
    "scan_images",
    "extracted_fields",
    "findings",
    "reports",
    "cases",
    "rule_versions",
    "audit_log",
}


def _alembic_config(url: str) -> Config:
    config = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    # What any in-process caller should do: run the migration without letting it
    # reconfigure the host process's logging. See the note in alembic/env.py.
    config.attributes["configure_logger"] = False
    return config


def _migrated(tmp_path, monkeypatch) -> str:
    """Run every migration against a throwaway database and return its URL.

    env.py reads the URL from settings rather than the ini on purpose — a migration must
    not be able to run against a different database than the API — so the override has
    to happen on settings.
    """
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setattr("app.core.config.settings.database_url", url)
    command.upgrade(_alembic_config(url), "head")
    return url


def test_upgrade_creates_every_table_the_application_expects(tmp_path, monkeypatch):
    url = _migrated(tmp_path, monkeypatch)
    inspector = sa.inspect(sa.create_engine(url))
    assert set(inspector.get_table_names()).issuperset(EXPECTED_TABLES)


def test_the_migrations_still_describe_the_models(tmp_path, monkeypatch):
    """The drift guard.

    Autogenerate against a fully migrated database must find nothing left to do. If it
    finds something, a model was changed without a migration, and the schema the tests
    run on is not the schema that will be deployed.
    """
    url = _migrated(tmp_path, monkeypatch)
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        difference = compare_metadata(context, Base.metadata)
    assert difference == [], (
        "models and migrations disagree; run `alembic revision --autogenerate` "
        f"and review the result:\n{difference}"
    )


def test_downgrade_leaves_nothing_behind(tmp_path, monkeypatch):
    """A migration that cannot be reversed cannot be safely rolled forward either."""
    url = _migrated(tmp_path, monkeypatch)
    command.downgrade(_alembic_config(url), "base")

    inspector = sa.inspect(sa.create_engine(url))
    remaining = set(inspector.get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_running_a_migration_does_not_switch_off_application_logging(tmp_path, monkeypatch, caplog):
    """A migration must not take the rest of the system's logging with it.

    alembic's env.py configures logging from alembic.ini, and `fileConfig` disables
    every already-configured logger unless told otherwise. That silently muted
    `app.rules.loader` for the remainder of the process — so a scan dated before any
    ruleset existed stopped warning that it was being judged by rules that post-date
    it. The warning is the only signal an officer gets that the citation on their
    report may be anachronistic, and losing it is not a logging inconvenience.
    """
    import logging
    from datetime import date

    from app.rules.loader import ruleset_for_date

    _migrated(tmp_path, monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.rules.loader"):
        ruleset_for_date(date(2015, 6, 1))
    assert any("2015-06-01" in r.getMessage() for r in caplog.records), (
        "the ruleset-dating warning was lost after a migration ran in-process"
    )


def test_the_api_refuses_to_file_scans_on_a_stale_schema(tmp_path, monkeypatch):
    """A database behind its migrations must be a 503, not a 500 after the OCR ran.

    Writes against a stale schema fail on the missing column, which means the officer
    has already waited through the scan before losing it. The state is knowable up
    front, so it is checked up front.
    """
    import sqlalchemy as sa

    from app.core.schema_state import SchemaState, inspect_schema

    empty = tmp_path / "never-migrated.db"
    empty.touch()
    engine = sa.create_engine(f"sqlite:///{empty.as_posix()}")
    report = inspect_schema(engine)
    assert report.state is SchemaState.UNINITIALISED
    assert report.writable is False
    assert "alembic upgrade head" in report.message

    url = _migrated(tmp_path, monkeypatch)
    assert inspect_schema(sa.create_engine(url)).writable is True


def test_findings_keep_the_original_status_alongside_an_override(tmp_path, monkeypatch):
    """Schema-level check of an invariant the API layers will depend on.

    An officer's override must not overwrite what the machine decided — both have to
    remain readable, or the audit trail records only the conclusion and not the
    disagreement. That requires original_status to be its own nullable column.
    """
    url = _migrated(tmp_path, monkeypatch)
    columns = {c["name"]: c for c in sa.inspect(sa.create_engine(url)).get_columns("findings")}

    assert "status" in columns
    assert "original_status" in columns
    assert columns["original_status"]["nullable"] is True
    for required in ("rule_id", "citation", "override_reason", "overridden_by_id"):
        assert required in columns, f"findings.{required} is needed to audit an override"
