"""The scan endpoint, and the invariants it must carry across the HTTP boundary.

The rule engine already refuses to invent violations, refuses to measure without a
scale, and refuses to call an open question a result. None of that survives on its own
once the output is serialised — a response shape that drops confidence, or lets a score
travel without its coverage, re-opens exactly the failures the engine closed. These
tests hold the boundary at the API the way test_rule_contract holds it at the engine.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.enums import FindingStatus, Verdict
from app.pipeline import engine_ocr
from app.pipeline.ocr import OcrBlock

API = "/api/v1"


# --------------------------------------------------------------------------- fixtures


COMPLIANT_LINES = [
    "Sunrise Foods",
    "Roasted Chana Masala",
    "Manufactured by: Sunrise Foods Private Limited",
    "Plot 14, MIDC Ambad",
    "Nashik, Maharashtra 422010",
    "Net Qty: 200 g",
    "MRP Rs. 45.00",
    "(inclusive of all taxes)",
    "Rs. 0.23 per g",
    "Mfd. 03/2026",
    "Batch No: RC2603A",
    "Consumer Care: Sunrise Foods Pvt Ltd",
    "Plot 14, MIDC Ambad, Nashik 422010",
    "care@sunrisefoods.in",
    "Toll free 1800 200 1234",
]


class ScriptedEngine:
    """Returns a fixed set of blocks, so an API test is not also an OCR test.

    The API's job is to carry the engine's verdict faithfully. Feeding it real OCR would
    make every assertion here contingent on recognition accuracy, and a flaky OCR read
    would look like an API regression. The real recognition path is exercised by the
    slow end-to-end test below and by the pipeline suite.
    """

    name = "scripted"

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def read(self, image: np.ndarray, image_id: str | None = None) -> list[OcrBlock]:
        blocks = []
        for i, text in enumerate(self.lines):
            top = 20.0 + i * 40.0
            width = 12.0 * len(text)
            blocks.append(
                OcrBlock(
                    text=text,
                    polygon=[
                        [20.0, top],
                        [20.0 + width, top],
                        [20.0 + width, top + 22.0],
                        [20.0, top + 22.0],
                    ],
                    confidence=0.94,
                    image_id=image_id,
                )
            )
        return blocks


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def scripted(request):
    """Install a scripted OCR engine for one test and put the real one back after."""
    lines = getattr(request, "param", COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(lines))
    yield
    engine_ocr._engine = previous


def png(width: int = 900, height: int = 700, fill: int = 245) -> bytes:
    image = np.full((height, width, 3), fill, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def upload(client, *, files=None, **form):
    files = files or [("images", ("front.png", png(), "image/png"))]
    return client.post(f"{API}/scans:analyze", files=files, data=form)


# ------------------------------------------------------------------------ happy path


def test_health_reports_what_is_actually_loaded(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok"
    assert body["rulesets"]
    # Named, not asserted: a server on the stub engine reads nothing, and an operator
    # needs to be able to see that rather than infer it from every scan coming back
    # inconclusive.
    assert body["ocr_engine"]


def test_a_clean_label_photographed_without_a_scale_is_not_certified(client, scripted):
    """Every declaration is correct, and the verdict is still not COMPLIANT.

    There is no scale card in this frame, so Rule 8 cannot be decided, and a package
    with an undecided mandatory rule has not been shown to comply — it has been shown
    not to fail. The engine draws that distinction; this asserts the API keeps it,
    because upgrading "nothing failed" to "compliant" is how an unmeasured pack
    acquires a clean bill of health.
    """
    body = upload(client).json()
    assert body["assessment"]["failed"] == 0
    assert body["assessment"]["verdict"] == Verdict.INCONCLUSIVE
    assert body["assessment"]["needs_review"] > 0
    assert body["ruleset_version"]
    assert body["images"][0]["blocks_read"] == len(COMPLIANT_LINES)


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_a_missing_tax_rider_is_reported_as_a_violation(client, scripted):
    body = upload(client).json()
    assert body["assessment"]["verdict"] == Verdict.NON_COMPLIANT
    failed = [f for f in body["findings"] if f["status"] == FindingStatus.FAIL]
    assert [f["rule_id"] for f in failed] == ["MRP_INCLUSIVE_OF_TAXES"]


def test_the_ruleset_in_force_on_the_scan_date_is_the_one_applied(client, scripted):
    """A 2019 pack must not be judged against a rule that arrived in 2022."""
    recent = upload(client, scan_date="2026-01-01").json()
    old = upload(client, scan_date="2019-06-01").json()
    assert recent["scan_date"] == "2026-01-01"
    assert old["scan_date"] == "2019-06-01"
    # Both resolve to a real ruleset; which one is the loader's decision, not the API's.
    assert recent["ruleset_version"] and old["ruleset_version"]


# ------------------------------------------------------------------- the invariants


def test_every_failure_carries_its_rule_citation_and_evidence(client, scripted):
    """A FAIL stripped of its provenance is an accusation with nothing behind it."""
    body = upload(
        client,
        files=[("images", ("front.png", png(), "image/png"))],
    ).json()
    for finding in body["findings"]:
        assert finding["rule_id"]
        assert finding["citation"]
        assert finding["evidence"] is not None
        if finding["status"] == FindingStatus.FAIL:
            evidence = finding["evidence"]
            # Either the declaration was located — and then its confidence and pixels
            # travel with the finding — or the response says plainly that it was not.
            if evidence["located"]:
                assert evidence["confidence"] is not None
                assert evidence["field_key"]
            else:
                assert evidence["note"]


def test_needs_review_is_never_marked_decided(client, scripted):
    body = upload(client).json()
    for finding in body["findings"]:
        expected = finding["status"] in (FindingStatus.PASS, FindingStatus.FAIL)
        assert finding["decided"] is expected


def test_a_score_cannot_be_read_without_its_coverage(client, scripted):
    """Structural, not advisory: the score has no home outside this object."""
    body = upload(client).json()
    assert "score" not in body
    assessment = body["assessment"]
    assert {"score", "rules_decided", "rules_applicable", "verdict"} <= set(assessment)
    assert assessment["rules_applicable"] >= assessment["rules_decided"]


def test_an_unreadable_image_is_inconclusive_and_accuses_nobody(client):
    """A lens cap is not a label with fifteen declarations missing.

    The engine already refuses to assert absence from a scan that read nothing. This
    checks the API reports that refusal rather than serialising a confident zero.
    """
    body = upload(client).json()  # real engine, blank image: nothing to read
    assert body["assessment"]["verdict"] == Verdict.INCONCLUSIVE
    assert body["assessment"]["failed"] == 0
    assert body["assessment"]["score"] is None
    assert body["notes"]


def test_no_millimetre_claim_survives_without_calibration(client, scripted):
    """No fiducial in frame, so nothing in the response may read as measured."""
    body = upload(client).json()
    calibration = body["calibration"]
    assert calibration["calibrated"] is False
    assert calibration["mm_per_px"] is None

    for field in body["fields"]:
        assert field["glyph_height_mm"] is None
        assert field["glyph_width_mm"] is None

    # And the geometry rules went to an officer rather than failing on a guess.
    geometry = [f for f in body["findings"] if f["rule_id"].startswith("FONT_")]
    assert geometry
    assert all(f["status"] != FindingStatus.FAIL for f in geometry)


def test_no_request_parameter_can_supply_a_scale(client, scripted):
    """The bypass this endpoint must not have.

    A client that could post mm_per_px could manufacture measured Rule 8 findings for a
    photograph with no reference in it at all.
    """
    body = upload(client, mm_per_px="0.08", scale_source="ARUCO").json()
    assert body["calibration"]["calibrated"] is False
    assert body["calibration"]["mm_per_px"] is None


def test_passing_rules_are_returned_too(client, scripted):
    """"What did you check" is part of the finding."""
    statuses = {f["status"] for f in upload(client).json()["findings"]}
    assert FindingStatus.PASS in statuses


# ----------------------------------------------------------------- malformed input


def test_no_images_is_rejected(client):
    assert client.post(f"{API}/scans:analyze", data={}).status_code == 422


def test_a_file_that_is_not_an_image_is_rejected(client):
    response = upload(
        client, files=[("images", ("notes.png", b"this is not a png", "image/png"))]
    )
    assert response.status_code == 400
    assert "could not be decoded" in response.json()["detail"]


def test_an_empty_file_is_rejected(client):
    response = upload(client, files=[("images", ("front.png", b"", "image/png"))])
    assert response.status_code == 400


def test_an_unsupported_content_type_is_rejected(client):
    response = upload(
        client, files=[("images", ("scan.pdf", b"%PDF-1.7", "application/pdf"))]
    )
    assert response.status_code == 400
    assert "application/pdf" in response.json()["detail"]


def test_an_image_too_small_to_carry_a_declaration_is_rejected(client):
    response = upload(client, files=[("images", ("tiny.png", png(10, 10), "image/png"))])
    assert response.status_code == 400
    assert "too small" in response.json()["detail"]


def test_too_many_images_are_rejected(client):
    files = [("images", (f"{i}.png", png(), "image/png")) for i in range(9)]
    assert upload(client, files=files).status_code == 413


def test_an_unknown_coin_is_rejected_rather_than_ignored(client, scripted):
    """Silently ignoring it would measure against the wrong diameter."""
    response = upload(client, coin="INR_2")
    assert response.status_code == 422
    assert "INR_2" in response.json()["detail"]


def test_image_kinds_must_match_the_images(client, scripted):
    response = upload(client, kinds="FRONT,BACK")
    assert response.status_code == 400


def test_an_unknown_image_kind_is_rejected(client, scripted):
    response = upload(client, kinds="TOP")
    assert response.status_code == 400
    assert "TOP" in response.json()["detail"]


def test_an_unknown_channel_is_rejected(client, scripted):
    assert upload(client, channel="TELEGRAM").status_code == 422


def test_an_unparseable_scan_date_is_rejected(client, scripted):
    assert upload(client, scan_date="last tuesday").status_code == 422


def test_an_unknown_ruleset_version_is_a_404(client):
    assert client.get(f"{API}/rulesets/1998-01-01").status_code == 404


# ------------------------------------------------------------------- real end to end


@pytest.mark.slow
def test_a_rendered_label_scans_end_to_end_through_real_ocr():
    """The whole chain: render a label, encode it, post it, read the verdict.

    Everything above stubs recognition. This one does not, so a break in the wiring
    between the HTTP layer and the pipeline shows up here even when the shapes are
    right.
    """
    from app.pipeline import synth

    image = synth.render(synth.compliant_label())
    ok, buf = cv2.imencode(".png", image)
    assert ok

    with TestClient(create_app()) as client:
        response = client.post(
            f"{API}/scans:analyze",
            files=[("images", ("label.png", buf.tobytes(), "image/png"))],
        )
    assert response.status_code == 200
    body = response.json()

    # The scale card is in the frame, so this scan is entitled to measure.
    assert body["calibration"]["calibrated"] is True
    assert body["calibration"]["source"] == "ARUCO"
    assert body["images"][0]["blocks_read"] > 5
    assert body["assessment"]["rules_applicable"] > 0
    assert [f for f in body["fields"] if f["field_key"] == "mrp"]

    # The label reads clean: nothing failed, and every rule the images can settle was
    # settled. The verdict is still INCONCLUSIVE, and correctly so — Rule 9's
    # misleading-declaration check is a judgement about meaning that the regex
    # extractor does not make, so it stays open for an officer rather than being
    # closed by a default. Certification therefore needs a human here, by design.
    assessment = body["assessment"]
    assert assessment["failed"] == 0
    assert assessment["score"] == 100.0
    assert assessment["needs_review"] == 1
    assert assessment["verdict"] == Verdict.INCONCLUSIVE
    open_rules = [f["rule_id"] for f in body["findings"] if f["status"] == "NEEDS_REVIEW"]
    assert open_rules == ["NO_MISLEADING_DECLARATION"]
