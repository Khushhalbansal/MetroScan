"""Filing a scan, and getting back exactly what was filed.

The failure this suite exists to prevent is quiet: a scan is shown to an officer, filed,
and reopened weeks later reading differently — a confidence rounded away, an override
that replaced the machine's finding instead of sitting beside it, an evidence image no
longer reachable. None of that raises an error. It just makes the record wrong.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.models.enums import FindingStatus, Role, Verdict
from app.pipeline import engine_ocr
from tests.authfixtures import API, OFFICER_PASSWORD, auth, build_app, seed_user, token_for
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OFFICER_EMAIL = "officer@metrology.gov.in"


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """An app on a throwaway database, with a signed-in officer.

    The schema is built by running the migrations, not by `Base.metadata.create_all`.
    That distinction is not academic: create_all builds the schema the models describe,
    which is by definition the one the ORM is about to write to, so it can never
    disagree with itself. A deployed server runs migrations instead, and the first
    version of this fixture used create_all and passed green while a real server
    returned 500 on every filed scan — the migration for four provenance columns
    existed but had not been applied. Testing against the migrated schema is what
    makes that a failing test rather than a production incident.
    """
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    with client:
        client.headers.update(auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD)))
        yield client


@pytest.fixture
def scripted(request):
    lines = getattr(request, "param", COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(lines))
    yield
    engine_ocr._engine = previous


def file_scan(client, *, product_name="Roasted Chana Masala", **form):
    return client.post(
        f"{API}/scans",
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": product_name, **form},
    )


# ------------------------------------------------------------------------- filing


def test_a_scan_is_filed_and_addressable(db_client, scripted):
    response = file_scan(db_client)
    assert response.status_code == 201
    body = response.json()
    assert body["scan_id"]
    assert body["product_id"]
    assert body["product_name"] == "Roasted Chana Masala"

    again = db_client.get(f"{API}/scans/{body['scan_id']}")
    assert again.status_code == 200


def test_what_is_filed_is_exactly_what_was_returned(db_client, scripted):
    """POST and GET must not be two renderings of the same scan.

    The POST response is rebuilt from the stored rows precisely so this holds. If it
    were returned from memory, a column that silently failed to persist would show up
    only when someone reopened the record.
    """
    filed = file_scan(db_client).json()
    reopened = db_client.get(f"{API}/scans/{filed['scan_id']}").json()

    assert filed["assessment"] == reopened["assessment"]
    assert filed["calibration"] == reopened["calibration"]
    assert filed["findings"] == reopened["findings"]
    assert filed["fields"] == reopened["fields"]
    assert filed["notes"] == reopened["notes"]


def test_re_scanning_one_product_keeps_one_timeline(db_client, scripted):
    """Two inspections of the same pack must not become two unrelated products."""
    first = file_scan(db_client, brand="Sunrise").json()
    second = file_scan(db_client, brand="Sunrise").json()
    assert first["product_id"] == second["product_id"]
    assert first["scan_id"] != second["scan_id"]


def test_the_ruleset_that_judged_a_scan_is_the_one_it_is_reopened_under(db_client, scripted):
    filed = file_scan(db_client, scan_date="2023-05-04").json()
    reopened = db_client.get(f"{API}/scans/{filed['scan_id']}").json()
    assert reopened["ruleset_version"] == filed["ruleset_version"]
    assert reopened["scan_date"] == "2023-05-04"


# --------------------------------------------------------------------- invariants


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_a_stored_failure_keeps_its_citation_and_confidence(db_client, scripted):
    """Persisting a finding must not be where its provenance gets dropped."""
    filed = file_scan(db_client).json()
    reopened = db_client.get(f"{API}/scans/{filed['scan_id']}").json()

    failures = [f for f in reopened["findings"] if f["status"] == FindingStatus.FAIL]
    assert failures
    for finding in failures:
        assert finding["rule_id"] and finding["citation"]
        evidence = finding["evidence"]
        assert evidence["located"] or evidence["note"]
        if evidence["located"]:
            assert evidence["confidence"] is not None
            assert evidence["image_id"]


def test_an_evidence_image_stays_reachable(db_client, scripted):
    """A finding whose image cannot be retrieved is an accusation nobody can check."""
    filed = file_scan(db_client).json()
    scan_id = filed["scan_id"]
    image_id = filed["images"][0]["image_id"]

    response = db_client.get(f"{API}/scans/{scan_id}/images/{image_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    decoded = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (filed["images"][0]["height"], filed["images"][0]["width"])


def test_an_unreadable_scan_files_as_inconclusive_with_no_violations(db_client):
    """The lens-cap case, but persisted. A stored zero would be a stored accusation."""
    filed = file_scan(db_client).json()  # real engine, blank image
    assert filed["assessment"]["verdict"] == Verdict.INCONCLUSIVE
    assert filed["assessment"]["score"] is None
    assert filed["assessment"]["failed"] == 0
    assert filed["notes"]

    reopened = db_client.get(f"{API}/scans/{filed['scan_id']}").json()
    assert reopened["assessment"]["score"] is None
    assert reopened["notes"] == filed["notes"]


def test_an_uncalibrated_scan_stores_no_millimetres(db_client, scripted):
    filed = file_scan(db_client).json()
    reopened = db_client.get(f"{API}/scans/{filed['scan_id']}").json()
    assert reopened["calibration"]["calibrated"] is False
    assert reopened["calibration"]["mm_per_px"] is None
    assert all(f["glyph_height_mm"] is None for f in reopened["fields"])


def test_a_filed_scan_carries_no_override_until_an_officer_makes_one(db_client, scripted):
    filed = file_scan(db_client).json()
    assert all(f["override"] is None for f in filed["findings"])


def test_the_ocr_blocks_are_kept_so_a_scan_can_be_rejudged(db_client, scripted):
    """An amended ruleset must not require re-photographing the pack."""
    filed = file_scan(db_client).json()
    assert filed["images"][0]["blocks_read"] == len(COMPLIANT_LINES)


# ------------------------------------------------------------------------- search


def test_scans_can_be_found_by_verdict(db_client, scripted):
    file_scan(db_client, product_name="Alpha")
    page = db_client.get(f"{API}/scans", params={"verdict": "INCONCLUSIVE"}).json()
    assert page["total"] >= 1
    assert all(s["verdict"] == "INCONCLUSIVE" for s in page["scans"])


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_scans_can_be_found_by_the_rule_they_failed(db_client, scripted):
    """The enforcement question: which packs failed this rule."""
    file_scan(db_client, product_name="Beta")
    page = db_client.get(
        f"{API}/scans", params={"rule_id": "MRP_INCLUSIVE_OF_TAXES"}
    ).json()
    assert page["total"] == 1

    none = db_client.get(f"{API}/scans", params={"rule_id": "MRP_PRESENT"}).json()
    assert none["total"] == 0


def test_a_listing_row_carries_coverage_beside_its_score(db_client, scripted):
    """A list view is exactly where a lone number gets skimmed as a grade."""
    file_scan(db_client)
    row = db_client.get(f"{API}/scans").json()["scans"][0]
    assert {"verdict", "score", "rules_decided", "rules_applicable"} <= set(row)


def test_paging_reports_the_total_before_the_page(db_client, scripted):
    for i in range(3):
        file_scan(db_client, product_name=f"Product {i}")
    page = db_client.get(f"{API}/scans", params={"limit": 2}).json()
    assert page["total"] == 3
    assert len(page["scans"]) == 2


# ------------------------------------------------------------------ malformed input


def test_filing_without_a_product_name_is_rejected(db_client, scripted):
    response = db_client.post(
        f"{API}/scans", files=[("images", ("f.png", png(), "image/png"))], data={}
    )
    assert response.status_code == 422


def test_filing_an_undecodable_image_is_rejected(db_client):
    response = db_client.post(
        f"{API}/scans",
        files=[("images", ("f.png", b"not an image", "image/png"))],
        data={"product_name": "X"},
    )
    assert response.status_code == 400


def test_an_unknown_scan_is_a_404(db_client):
    assert db_client.get(f"{API}/scans/{'0' * 32}").status_code == 404


def test_an_unknown_evidence_image_is_a_404(db_client, scripted):
    scan_id = file_scan(db_client).json()["scan_id"]
    assert db_client.get(f"{API}/scans/{scan_id}/images/{'0' * 32}").status_code == 404


def test_an_image_cannot_be_fetched_through_the_wrong_scan(db_client, scripted):
    """Addressing evidence by scan is what stops the store being browsable."""
    first = file_scan(db_client, product_name="One").json()
    second = file_scan(db_client, product_name="Two").json()
    response = db_client.get(
        f"{API}/scans/{first['scan_id']}/images/{second['images'][0]['image_id']}"
    )
    assert response.status_code == 404


def test_filing_is_refused_when_the_database_is_behind_its_migrations(tmp_path, monkeypatch):
    """503 before the work, not 500 after it.

    This is the failure that got past the first version of these tests: the fixture
    built its schema with create_all, so it could never be out of date, while a real
    server on an un-upgraded database threw OperationalError on every filed scan.

    Checked at the sign-in endpoint, which is the first write any caller reaches on a
    stale server — and reaching it without a token proves the schema gate does not
    depend on authentication succeeding first.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import get_db
    from app.main import create_app

    monkeypatch.setattr("app.core.config.settings.storage_dir", tmp_path / "storage")
    stale = tmp_path / "stale.db"
    stale.touch()
    engine = create_engine(
        f"sqlite:///{stale.as_posix()}", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: Session()
    with TestClient(app) as client:
        response = client.post(
            f"{API}/auth/login", json={"email": "a@b.gov.in", "password": "x" * 12}
        )
    assert response.status_code == 503
    assert "alembic upgrade head" in response.json()["detail"]


def test_reading_is_still_possible_on_a_stale_schema():
    """Only writes are gated. A stale server must still answer its own health check."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get(f"{API}/health").status_code == 200


def test_a_storage_key_cannot_climb_out_of_the_store(tmp_path, monkeypatch):
    """Keys come from the database; a traversal in one must not serve arbitrary files."""
    from app.services import storage

    monkeypatch.setattr("app.core.config.settings.storage_dir", tmp_path / "storage")
    (tmp_path / "storage").mkdir()
    with pytest.raises(storage.StorageError, match="escapes the store"):
        storage.path_of("../../../../windows/win.ini")
