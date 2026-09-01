"""Editing a filed scan's photographs.

The failure this suite exists to prevent is a finding that outlives its evidence: an
officer deletes the blurred frame a violation was read from, and the violation stays on
screen anyway. So the tests do not check that a status flag flipped — they check that
the findings themselves changed to match the new image set, which is only possible if
the pipeline genuinely ran again.
"""

from __future__ import annotations

import io

import cv2
import numpy as np
import pytest

from app.models.enums import Role
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

OFFICER_EMAIL = "officer@metrology.gov.in"
OTHER_EMAIL = "other.officer@metrology.gov.in"
ADMIN_EMAIL = "controller@metrology.gov.in"

NO_TAX_RIDER = [line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]


class SwitchableEngine:
    """An OCR engine whose output can be changed between calls.

    This is what makes "did it actually re-run?" answerable. If a route only flipped a
    status, the findings would still reflect the lines the first run saw; because the
    engine returns something different on the second call, findings that changed prove
    the pipeline was executed again.
    """

    name = "switchable"

    def __init__(self, lines):
        self.lines = list(lines)
        self.calls = 0

    def read(self, image, image_id=None):
        self.calls += 1
        return ScriptedEngine(self.lines).read(image, image_id)


@pytest.fixture
def bench(tmp_path, monkeypatch):
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=OTHER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    seed_user(Session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, role=Role.ADMIN)

    engine = SwitchableEngine(COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(engine)
    with client:
        client.headers.update(auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD)))
        yield client, engine
    engine_ocr._engine = previous


def file_scan(client, images=1):
    files = [("images", (f"front{i}.png", png(), "image/png")) for i in range(images)]
    response = client.post(
        f"{API}/scans", files=files, data={"product_name": "Roasted Chana Masala"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(name="added.png"):
    return {"image": (name, png(), "image/png")}


# ------------------------------------------------------------------- adding a photo


def test_adding_a_photograph_re_runs_the_pipeline(bench):
    """The core claim: findings reflect the new image set, not a cached one.

    The engine is switched to a set of lines missing the tax rider before the image is
    added. If the route only marked the scan as changed, the findings would still say
    the rider was present.
    """
    client, engine = bench
    scan = file_scan(client)
    assert scan["assessment"]["failed"] == 0

    engine.lines = NO_TAX_RIDER
    calls_before = engine.calls

    response = client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())
    assert response.status_code == 201, response.text
    body = response.json()

    assert engine.calls > calls_before, "OCR never ran again"
    failed = [f["rule_id"] for f in body["findings"] if f["status"] == "FAIL"]
    assert "MRP_INCLUSIVE_OF_TAXES" in failed
    assert body["assessment"]["verdict"] == "NON_COMPLIANT"
    assert len(body["images"]) == 2
    assert body["revision"] == 2


def test_a_scan_cannot_hold_more_photographs_than_a_check_accepts(bench):
    client, _ = bench
    scan = file_scan(client, images=8)
    response = client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())
    assert response.status_code == 409
    assert "Remove one first" in response.json()["detail"]


def test_an_undecodable_addition_is_refused_before_anything_changes(bench):
    client, _ = bench
    scan = file_scan(client)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/images",
        files={"image": ("x.png", b"not an image", "image/png")},
    )
    assert response.status_code == 400

    unchanged = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert unchanged["revision"] == 1
    assert len(unchanged["images"]) == 1


def test_an_unknown_image_kind_is_refused(bench):
    client, _ = bench
    scan = file_scan(client)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/images", files=upload(), data={"kind": "TOP"}
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- removing a photo


def test_removing_a_photograph_re_runs_the_pipeline(bench):
    client, engine = bench
    scan = file_scan(client, images=2)
    image_id = scan["images"][0]["image_id"]

    engine.lines = NO_TAX_RIDER
    calls_before = engine.calls

    response = client.delete(f"{API}/scans/{scan['scan_id']}/images/{image_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert engine.calls > calls_before
    assert len(body["images"]) == 1
    assert body["revision"] == 2
    assert "MRP_INCLUSIVE_OF_TAXES" in [
        f["rule_id"] for f in body["findings"] if f["status"] == "FAIL"
    ]


def test_the_last_photograph_cannot_be_removed(bench):
    """A scan with no images is not a pack with everything missing — it is a record
    with no evidence at all, and the engine would have nothing to refuse to judge."""
    client, _ = bench
    scan = file_scan(client)
    response = client.delete(
        f"{API}/scans/{scan['scan_id']}/images/{scan['images'][0]['image_id']}"
    )
    assert response.status_code == 409
    assert "at least one photograph" in response.json()["detail"]


def test_removing_an_unknown_photograph_is_a_404(bench):
    client, _ = bench
    scan = file_scan(client, images=2)
    assert client.delete(f"{API}/scans/{scan['scan_id']}/images/{'0' * 32}").status_code == 404


# ---------------------------------------------------------------- retaking a photo


def test_retaking_a_photograph_re_runs_the_pipeline_and_keeps_the_slot(bench):
    client, engine = bench
    scan = file_scan(client)
    image_id = scan["images"][0]["image_id"]

    engine.lines = NO_TAX_RIDER
    calls_before = engine.calls

    response = client.post(
        f"{API}/scans/{scan['scan_id']}/images/{image_id}:replace",
        files={"image": ("retaken.png", png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert engine.calls > calls_before
    # The row keeps its id, so a finding's evidence still points at the same slot.
    assert body["images"][0]["image_id"] == image_id
    assert body["images"][0]["filename"] == "retaken.png"
    assert body["revision"] == 2


def test_the_retaken_pixels_actually_replace_the_old_ones(bench):
    """The stored bytes must change, not just the row's metadata."""
    client, _ = bench
    scan = file_scan(client)
    image_id = scan["images"][0]["image_id"]

    before = client.get(f"{API}/scans/{scan['scan_id']}/images/{image_id}").content
    client.post(
        f"{API}/scans/{scan['scan_id']}/images/{image_id}:replace",
        files={"image": ("retaken.png", png(width=1000, height=800, fill=200), "image/png")},
    )
    after = client.get(f"{API}/scans/{scan['scan_id']}/images/{image_id}").content

    assert before != after
    decoded = cv2.imdecode(np.frombuffer(after, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (800, 1000)


# ------------------------------------------------------------------------- history


def test_the_previous_reading_is_kept_and_queryable(bench):
    """An edit moves a result into history; it never discards it."""
    client, engine = bench
    scan = file_scan(client)
    assert scan["assessment"]["failed"] == 0

    engine.lines = NO_TAX_RIDER
    client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())

    revisions = client.get(f"{API}/scans/{scan['scan_id']}/revisions").json()
    assert len(revisions) == 1
    kept = revisions[0]
    assert kept["revision"] == 1
    assert kept["reason"] == "image added"
    assert kept["superseded_by_id"]
    # The superseded reading still says what it said. INCONCLUSIVE rather than
    # COMPLIANT because these fixtures photograph the pack without a scale card, so
    # Rule 8 was never decided — a clean label nobody could measure is not certified.
    assert kept["snapshot"]["assessment"]["failed"] == 0
    assert kept["snapshot"]["assessment"]["verdict"] == "INCONCLUSIVE"
    assert kept["snapshot"]["assessment"]["needs_review"] > 0


def test_an_officer_decision_survives_in_history_but_is_not_carried_forward(bench):
    """An override is a judgement about evidence that no longer exists.

    Re-applying it to a finding read from different photographs would carry a human
    decision onto something it was never made about — so it is preserved in the
    snapshot and the officer is asked again.
    """
    client, engine = bench
    engine.lines = NO_TAX_RIDER
    scan = file_scan(client)

    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        json={"status": "PASS", "reason": "Rider is on the reverse panel, checked by hand."},
    )
    overridden = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert overridden["assessment"]["overridden"] == 1

    client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())

    current = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert current["assessment"]["overridden"] == 0
    assert all(f["override"] is None for f in current["findings"])

    kept = client.get(f"{API}/scans/{scan['scan_id']}/revisions").json()[0]
    finding = next(
        f for f in kept["snapshot"]["findings"] if f["rule_id"] == "MRP_INCLUSIVE_OF_TAXES"
    )
    assert finding["override"]["original_status"] == "FAIL"
    assert "reverse panel" in finding["override"]["reason"]


def test_every_edit_adds_a_revision(bench):
    client, _ = bench
    scan = file_scan(client, images=2)
    client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload("a.png"))
    client.delete(f"{API}/scans/{scan['scan_id']}/images/{scan['images'][0]['image_id']}")

    revisions = client.get(f"{API}/scans/{scan['scan_id']}/revisions").json()
    assert [r["revision"] for r in revisions] == [1, 2]
    assert [r["reason"] for r in revisions] == ["image added", "image removed"]
    assert client.get(f"{API}/scans/{scan['scan_id']}").json()["revision"] == 3


def test_the_scan_date_and_ruleset_are_not_re_dated_by_an_edit(bench):
    """Re-photographing a pack does not move it onto rules that did not exist then."""
    client, _ = bench
    response = client.post(
        f"{API}/scans",
        files=[("images", ("f.png", png(), "image/png"))],
        data={"product_name": "Old pack", "scan_date": "2023-05-04"},
    )
    scan = response.json()
    client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())

    after = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert after["scan_date"] == "2023-05-04"
    assert after["ruleset_version"] == scan["ruleset_version"]


# ----------------------------------------------------------------------- audit log


@pytest.mark.parametrize(
    ("action", "call"),
    [
        ("IMAGE_ADDED", "add"),
        ("IMAGE_REMOVED", "remove"),
        ("IMAGE_REPLACED", "replace"),
    ],
)
def test_every_edit_is_audit_logged(bench, action, call):
    client, _ = bench
    scan = file_scan(client, images=2)
    scan_id = scan["scan_id"]
    image_id = scan["images"][0]["image_id"]

    if call == "add":
        client.post(f"{API}/scans/{scan_id}/images", files=upload())
    elif call == "remove":
        client.delete(f"{API}/scans/{scan_id}/images/{image_id}")
    else:
        client.post(
            f"{API}/scans/{scan_id}/images/{image_id}:replace",
            files={"image": ("r.png", png(), "image/png")},
        )

    entries = client.get(f"{API}/auth/audit", params={"entity_type": "scan"}).json()
    entry = next(e for e in entries if e["action"] == action)
    assert entry["actor_email"] == OFFICER_EMAIL
    assert entry["entity_id"] == scan_id
    assert entry["before"]["revision"] == 1
    assert entry["after"]["revision"] == 2
    assert entry["after"]["detail"]


def test_the_audit_entry_records_how_many_officer_decisions_were_cleared(bench):
    client, engine = bench
    engine.lines = NO_TAX_RIDER
    scan = file_scan(client)
    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        json={"status": "PASS", "reason": "Rider is on the reverse panel, checked by hand."},
    )
    client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload())

    entries = client.get(f"{API}/auth/audit", params={"entity_type": "scan"}).json()
    entry = next(e for e in entries if e["action"] == "IMAGE_ADDED")
    assert entry["before"]["officer_decisions_cleared"] == 1


# ---------------------------------------------------------------------- permissions


def test_an_anonymous_caller_cannot_edit_photographs(bench):
    client, _ = bench
    scan = file_scan(client)
    anon = {"Authorization": ""}
    base = f"{API}/scans/{scan['scan_id']}/images"
    assert client.post(base, files=upload(), headers=anon).status_code == 401
    assert client.delete(f"{base}/{scan['images'][0]['image_id']}", headers=anon).status_code == 401
    assert client.get(f"{API}/scans/{scan['scan_id']}/revisions", headers=anon).status_code == 401


def test_another_officer_cannot_change_someone_elses_evidence(bench):
    """One officer silently replacing another's evidence is a change a record must be
    able to rule out."""
    client, _ = bench
    scan = file_scan(client)
    intruder = auth(token_for(client, OTHER_EMAIL, OFFICER_PASSWORD))

    response = client.post(
        f"{API}/scans/{scan['scan_id']}/images", files=upload(), headers=intruder
    )
    assert response.status_code == 403
    assert "another officer" in response.json()["detail"]

    unchanged = client.get(f"{API}/scans/{scan['scan_id']}").json()
    assert unchanged["revision"] == 1


def test_an_administrator_can_change_any_scans_photographs(bench):
    client, _ = bench
    scan = file_scan(client)
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))

    response = client.post(
        f"{API}/scans/{scan['scan_id']}/images", files=upload(), headers=admin
    )
    assert response.status_code == 201
    assert response.json()["revision"] == 2


def test_editing_an_unknown_scan_is_a_404(bench):
    client, _ = bench
    assert client.post(f"{API}/scans/{'0' * 32}/images", files=upload()).status_code == 404


# --------------------------------------------------------- invariants carried over


def test_an_edit_that_removes_the_scale_card_stops_claiming_millimetres(bench):
    """The measurement invariant has to survive an edit too.

    This uses a real rendered label with an ArUco card and then replaces it with a
    blank frame: the scan goes from calibrated to not, and no mm value may survive.
    """
    from app.pipeline import synth

    client, _ = bench
    engine_ocr.set_engine(engine_ocr.RapidOcrEngine())
    try:
        rendered = synth.render(synth.compliant_label())
        ok, buf = cv2.imencode(".png", rendered)
        assert ok
        created = client.post(
            f"{API}/scans",
            files=[("images", ("label.png", buf.tobytes(), "image/png"))],
            data={"product_name": "Calibrated pack"},
        )
        scan = created.json()
        assert scan["calibration"]["calibrated"] is True

        image_id = scan["images"][0]["image_id"]
        response = client.post(
            f"{API}/scans/{scan['scan_id']}/images/{image_id}:replace",
            files={"image": ("blank.png", png(), "image/png")},
        )
        body = response.json()

        assert body["calibration"]["calibrated"] is False
        assert body["calibration"]["mm_per_px"] is None
        assert all(f["glyph_height_mm"] is None for f in body["fields"])
        # And nothing was invented from a frame that read nothing.
        assert body["assessment"]["failed"] == 0
        assert body["assessment"]["score"] is None
    finally:
        engine_ocr.set_engine(ScriptedEngine(COMPLIANT_LINES))


def test_a_re_run_that_reads_nothing_does_not_invent_violations(bench):
    client, engine = bench
    scan = file_scan(client)
    engine.lines = []

    body = client.post(f"{API}/scans/{scan['scan_id']}/images", files=upload()).json()
    assert body["assessment"]["failed"] == 0
    assert body["assessment"]["verdict"] == "INCONCLUSIVE"
    assert body["assessment"]["score"] is None
    assert body["notes"]


def test_png_helper_supports_a_distinct_second_image():
    """Guards the fixture the retake test depends on."""
    a = png()
    b = png(width=1000, height=800, fill=200)
    assert a != b
    assert cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (800, 1000)
    assert io.BytesIO(a).read(8).startswith(b"\x89PNG")
