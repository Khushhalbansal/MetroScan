"""Manual soft-delete of a filed scan (Feature 5).

The shape of the feature, restated so the tests can be read against it:

  * Delete is a *soft* delete. The row, its images and its findings stay in the
    database; only `deleted_at` / `deleted_by_id` / `deleted_reason` are set. The audit
    trail keeps a `SCAN_DELETED` entry. Nothing is ever hard-deleted — the question
    "did this scan exist, and who removed it" must stay answerable forever.
  * An officer may delete a scan they filed. An administrator may delete any scan.
  * A case being open does **not** block a manual delete. That is an explicit act by an
    authorised person; only the scheduled auto-deletion job defers to `case_open`.
  * A deleted scan drops out of the repository listing unless `include_deleted=True`,
    and its evidence can no longer be edited.
"""

from __future__ import annotations

import pytest

from app.models.enums import Role
from app.models.tables import Scan
from app.pipeline import engine_ocr
from tests.authfixtures import (
    ADMIN_PASSWORD,
    API,
    OFFICER_PASSWORD,
    auth,
    build_app,
    seed_user,
    token_for,
)
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OWNER_EMAIL = "owner@metrology.gov.in"
OTHER_EMAIL = "other.officer@metrology.gov.in"
ADMIN_EMAIL = "controller@metrology.gov.in"


@pytest.fixture
def bench(tmp_path, monkeypatch):
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OWNER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=OTHER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, role=Role.ADMIN)

    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(COMPLIANT_LINES))
    with client:
        # Signed in as the scan's owner by default; other roles fetch their own token.
        client.headers.update(auth(token_for(client, OWNER_EMAIL, OFFICER_PASSWORD)))
        yield client, Session
    engine_ocr._engine = previous


def file_scan(client, name="Roasted Chana Masala"):
    r = client.post(
        f"{API}/scans",
        files=[("images", ("f.png", png(), "image/png"))],
        data={"product_name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def delete_scan(client, scan_id, *, reason=None, headers=None):
    """DELETE with an optional JSON body. TestClient needs `request` for a body on DELETE."""
    kwargs: dict = {}
    if reason is not None:
        kwargs["json"] = {"reason": reason}
    if headers is not None:
        kwargs["headers"] = headers
    return client.request("DELETE", f"{API}/scans/{scan_id}", **kwargs)


def row(Session, scan_id):
    """A detached copy for scalar-column assertions (`deleted_at`, `case_open`, ...).

    `db.get` eager-loads every column, so those stay readable after the session closes;
    relationship collections do not — use `child_counts` for those.
    """
    db = Session()
    try:
        return db.get(Scan, scan_id)
    finally:
        db.close()


def child_counts(Session, scan_id):
    """(findings, images) counts, read while the session is still open."""
    db = Session()
    try:
        scan = db.get(Scan, scan_id)
        return len(scan.findings), len(scan.images)
    finally:
        db.close()


def set_scan(Session, scan_id, **columns):
    db = Session()
    try:
        scan = db.get(Scan, scan_id)
        for key, value in columns.items():
            setattr(scan, key, value)
        db.commit()
    finally:
        db.close()


def audit_entries(client, scan_id):
    r = client.get(
        f"{API}/auth/audit", params={"entity_type": "scan", "entity_id": scan_id}
    )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------- the happy path


def test_an_officer_can_soft_delete_a_scan_they_filed(bench):
    client, Session = bench
    scan = file_scan(client)

    r = delete_scan(client, scan["scan_id"], reason="duplicate capture")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_at"] is not None
    assert body["deleted_reason"] == "duplicate capture"

    # Soft: the row, its images and its findings are all still there.
    stored = row(Session, scan["scan_id"])
    assert stored is not None
    assert stored.deleted_at is not None
    assert stored.deleted_by_id is not None
    findings, images = child_counts(Session, scan["scan_id"])
    assert findings > 0
    assert images > 0


def test_a_delete_needs_no_body(bench):
    client, _ = bench
    scan = file_scan(client)
    r = client.request("DELETE", f"{API}/scans/{scan['scan_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_reason"] is None


def test_a_deleted_scan_leaves_the_repository_listing(bench):
    client, _ = bench
    scan = file_scan(client, name="Vanishing pack")
    delete_scan(client, scan["scan_id"], reason="withdrawn")

    page = client.get(f"{API}/scans", params={"product_id": scan["product_id"]}).json()
    assert all(s["scan_id"] != scan["scan_id"] for s in page["scans"])

    with_deleted = client.get(
        f"{API}/scans",
        params={"product_id": scan["product_id"], "include_deleted": True},
    ).json()
    listed = next(s for s in with_deleted["scans"] if s["scan_id"] == scan["scan_id"])
    assert listed["deleted"] is True


def test_the_deleted_scan_is_still_readable_by_id(bench):
    """Soft delete removes it from the working list, not from the record."""
    client, _ = bench
    scan = file_scan(client)
    delete_scan(client, scan["scan_id"])
    got = client.get(f"{API}/scans/{scan['scan_id']}")
    assert got.status_code == 200
    assert got.json()["deleted_at"] is not None


# ------------------------------------------------------------- the permission boundary


def test_an_officer_cannot_delete_another_officers_scan(bench):
    client, Session = bench
    scan = file_scan(client)  # filed by OWNER

    other = auth(token_for(client, OTHER_EMAIL, OFFICER_PASSWORD))
    r = delete_scan(client, scan["scan_id"], headers=other)
    assert r.status_code == 403
    assert row(Session, scan["scan_id"]).deleted_at is None


def test_an_administrator_can_delete_any_scan(bench):
    client, Session = bench
    scan = file_scan(client)  # filed by OWNER

    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    r = delete_scan(client, scan["scan_id"], reason="controller review", headers=admin)
    assert r.status_code == 200, r.text
    assert row(Session, scan["scan_id"]).deleted_at is not None


def test_a_delete_needs_authentication(bench):
    client, Session = bench
    scan = file_scan(client)
    r = delete_scan(client, scan["scan_id"], headers={"Authorization": ""})
    assert r.status_code == 401
    assert row(Session, scan["scan_id"]).deleted_at is None


# ----------------------------------------------------------------- malformed / edge


def test_deleting_an_unknown_scan_is_a_404(bench):
    client, _ = bench
    assert delete_scan(client, "0" * 32).status_code == 404


def test_deleting_a_scan_twice_is_a_conflict(bench):
    client, _ = bench
    scan = file_scan(client)
    assert delete_scan(client, scan["scan_id"]).status_code == 200
    r = delete_scan(client, scan["scan_id"])
    assert r.status_code == 409
    assert "already deleted" in r.json()["detail"].lower()


def test_an_over_long_reason_is_rejected(bench):
    client, Session = bench
    scan = file_scan(client)
    r = delete_scan(client, scan["scan_id"], reason="x" * 65)
    assert r.status_code == 422
    assert row(Session, scan["scan_id"]).deleted_at is None


# ----------------------------------------------------- the case_open exception


def test_a_scan_with_a_case_open_is_still_manually_deletable(bench):
    """The spec calls this out explicitly: a manual delete is an authorised override and
    does not consult `case_open`. Only the automatic job respects it."""
    client, Session = bench
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True})

    r = delete_scan(client, scan["scan_id"], reason="pack recalled, record superseded")
    assert r.status_code == 200, r.text

    stored = row(Session, scan["scan_id"])
    assert stored.deleted_at is not None
    # The retention answer is preserved, not cleared — the deletion is the override.
    assert stored.case_open is True


# ----------------------------------------------------------------------- audit trail


def test_the_delete_is_audit_logged_with_actor_and_before_after(bench):
    client, _ = bench
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": False})
    delete_scan(client, scan["scan_id"], reason="filed in error")

    entries = audit_entries(client, scan["scan_id"])
    deletes = [e for e in entries if e["action"] == "SCAN_DELETED"]
    assert len(deletes) == 1
    entry = deletes[0]
    assert entry["actor_email"] == OWNER_EMAIL
    assert entry["before"] == {"deleted_at": None}
    assert entry["after"]["deleted_at"]
    assert entry["after"]["reason"] == "filed in error"
    assert entry["after"]["automated"] is False
    # The retention state at the moment of deletion is captured for later accountability.
    assert entry["after"]["case_open"] is False


def test_an_admin_delete_names_the_admin_in_the_log(bench):
    client, _ = bench
    scan = file_scan(client)
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    delete_scan(client, scan["scan_id"], headers=admin)

    deletes = [e for e in audit_entries(client, scan["scan_id"]) if e["action"] == "SCAN_DELETED"]
    assert len(deletes) == 1
    assert deletes[0]["actor_email"] == ADMIN_EMAIL
    assert deletes[0]["after"]["automated"] is False


# --------------------------------------------- a deleted scan's evidence is frozen


def test_a_deleted_scans_photographs_cannot_be_edited(bench):
    client, _ = bench
    scan = file_scan(client)
    delete_scan(client, scan["scan_id"])

    added = client.post(
        f"{API}/scans/{scan['scan_id']}/images",
        files={"image": ("extra.png", png(), "image/png")},
    )
    assert added.status_code == 409
    assert "deleted" in added.json()["detail"].lower()


def test_a_deleted_scans_findings_cannot_be_overridden(bench):
    client, _ = bench
    scan = file_scan(client)
    rule_id = scan["findings"][0]["rule_id"]
    delete_scan(client, scan["scan_id"])

    r = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/{rule_id}:override",
        json={"status": "FAIL", "reason": "checking the deleted-scan override guard"},
    )
    assert r.status_code == 409
    assert "deleted" in r.json()["detail"].lower()


def test_a_deleted_scan_cannot_take_a_new_retention_answer(bench):
    client, _ = bench
    scan = file_scan(client)
    delete_scan(client, scan["scan_id"])
    r = client.post(f"{API}/scans/{scan['scan_id']}/retention", json={"case_open": True})
    assert r.status_code == 404
