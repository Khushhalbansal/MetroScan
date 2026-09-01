"""The compliance report: the Measure, the PDF, and what must appear on paper.

A report is the artefact that leaves the building. Everything the invariants protect
inside the system — an open question not shown as a violation, a millimetre claim only
where there was a scale, an officer's override sitting beside the machine's finding
rather than on top of it — has to survive onto the page, because the page is what a
manufacturer contests and what an officer signs.
"""

from __future__ import annotations

import io
import json

import pytest

from app.models.enums import FindingStatus, Role
from app.pipeline import engine_ocr
from app.reports import measure
from tests.authfixtures import API, OFFICER_PASSWORD, auth, build_app, seed_user, token_for
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

OFFICER_EMAIL = "officer@metrology.gov.in"

NO_TAX_RIDER = [line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]


@pytest.fixture
def client(tmp_path, monkeypatch):
    c, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    with c:
        c.headers.update(auth(token_for(c, OFFICER_EMAIL, OFFICER_PASSWORD)))
        yield c


@pytest.fixture
def scripted(request):
    lines = getattr(request, "param", COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(lines))
    yield
    engine_ocr._engine = previous


def file_scan(client, **form):
    return client.post(
        f"{API}/scans",
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": "Roasted Chana Masala", **form},
    ).json()


# ------------------------------------------------------------------ the Measure


def test_a_measurement_below_the_limit_reads_as_a_shortfall():
    m = measure.build(measured_mm=1.4, required_mm=2.0)
    assert m.compliant is False
    assert m.shortfall_mm == 0.6
    assert m.measured_position < m.required_position


def test_a_measurement_at_the_limit_complies():
    m = measure.build(measured_mm=2.0, required_mm=2.0)
    assert m.compliant is True
    assert m.shortfall_mm is None
    assert m.measured_position == m.required_position


def test_an_unmeasured_declaration_still_shows_what_the_rule_requires():
    """No scale in frame. The requirement is drawn; nothing is indexed against it.

    Showing a blank ruler is honest — it states the limit while making plain that
    nothing was measured. Drawing an index at zero would read as "measured 0 mm",
    which is a finding nobody made.
    """
    m = measure.build(measured_mm=None, required_mm=2.0)
    assert m.measured_position is None
    assert m.shortfall_mm is None
    assert m.compliant is False
    assert m.required_position > 0


def test_the_scale_never_ends_at_the_measurement():
    """A 0.4 mm reading on a scale that stopped at 1 mm would read as a near miss."""
    m = measure.build(measured_mm=0.4, required_mm=1.0)
    assert m.scale_max_mm >= measure.MIN_SCALE_MM
    assert m.required_position < 100


def test_a_large_requirement_still_fits_on_the_scale():
    m = measure.build(measured_mm=5.0, required_mm=6.0)
    assert m.scale_max_mm > 6.0
    assert m.measured_position < 100 and m.required_position < 100


def test_graduations_are_uneven_so_the_rule_is_readable():
    """Tall at whole millimetres, short between — the thing that makes it a rule."""
    m = measure.build(measured_mm=1.4, required_mm=2.0)
    majors = [t for t in m.ticks if t.major]
    assert len(majors) == int(m.scale_max_mm) + 1
    assert all(t.mm == int(t.mm) for t in majors)
    assert any(not t.major for t in m.ticks)


def test_a_finding_without_a_measurement_gets_no_ruler():
    """Drawing one for a presence check would be inventing a reading."""
    assert measure.from_finding({"missing": ["consumer_care_email"]}) is None
    assert measure.from_finding({}) is None


def test_a_geometry_finding_becomes_a_measure():
    m = measure.from_finding(
        {"measured_mm": 1.0, "required_mm": 2.0, "pdp_area_cm2": 155.0, "table": "Rule 8, Table I"}
    )
    assert m is not None
    assert m.measured_mm == 1.0 and m.required_mm == 2.0
    assert m.pdp_area_cm2 == 155.0
    assert m.citation == "Rule 8, Table I"


def test_a_corrupt_measurement_does_not_crash_the_report():
    """Values reach here from stored JSON; never trust the type."""
    assert measure.from_finding({"required_mm": "not a number"}) is None
    broken = measure.from_finding({"required_mm": 2.0, "measured_mm": "?"})
    assert broken is not None and broken.measured_mm is None


# --------------------------------------------------------------- generating one


def test_a_report_is_generated_and_fetchable(client, scripted):
    scan = file_scan(client)
    created = client.post(f"{API}/scans/{scan['scan_id']}/report")
    assert created.status_code == 201
    body = created.json()
    assert body["engine"] in ("weasyprint", "xhtml2pdf")

    pdf = client.get(f"{API}/scans/{scan['scan_id']}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    assert len(pdf.content) > 1000


def test_the_json_report_carries_the_whole_record(client, scripted):
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/report")
    response = client.get(f"{API}/scans/{scan['scan_id']}/report.json")
    assert response.status_code == 200

    payload = json.loads(response.content)
    assert payload["report"]["generated_by"] == OFFICER_EMAIL
    assert "not a legal determination" in payload["report"]["disclaimer"]
    assert payload["scan"]["scan_id"] == scan["scan_id"]
    assert payload["scan"]["findings"]
    assert payload["scan"]["assessment"]["automated_verdict"]


def test_fetching_a_report_before_generating_one_says_so(client, scripted):
    scan = file_scan(client)
    response = client.get(f"{API}/scans/{scan['scan_id']}/report.pdf")
    assert response.status_code == 404
    assert "POST" in response.json()["detail"]


def test_a_report_for_an_unknown_scan_is_a_404(client):
    assert client.post(f"{API}/scans/{'0' * 32}/report").status_code == 404


def test_reports_are_not_public(client, scripted):
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/report")
    anonymous = {"Authorization": ""}
    base = f"{API}/scans/{scan['scan_id']}/report"
    assert client.post(base, headers=anonymous).status_code == 401
    assert client.get(f"{base}.pdf", headers=anonymous).status_code == 401
    assert client.get(f"{base}.json", headers=anonymous).status_code == 401


# --------------------------------------------------- what must appear on paper


def html_of(client, scan_id: str) -> str:
    """The report HTML with runs of whitespace collapsed.

    Prose in the template wraps for readability, so a sentence that reads as one line
    on the page contains newlines in the source. Asserting on the raw text would make
    these tests fail whenever someone rewraps a paragraph, which teaches people to stop
    rewrapping paragraphs.
    """
    response = client.get(f"{API}/scans/{scan_id}/report.html")
    assert response.status_code == 200
    return " ".join(response.text.split())


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_every_failure_on_the_page_carries_its_citation(client, scripted):
    """A violation printed without the rule it came from is an unsupported accusation."""
    scan = file_scan(client)
    html = html_of(client, scan["scan_id"])

    failures = [f for f in scan["findings"] if f["status"] == FindingStatus.FAIL]
    assert failures
    for finding in failures:
        assert finding["rule_id"] in html
        assert finding["citation"] in html


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_the_evidence_text_and_its_confidence_are_printed(client, scripted):
    scan = file_scan(client)
    html = html_of(client, scan["scan_id"])
    assert "MRP Rs. 45.00" in html
    assert "confidence" in html


def test_open_questions_are_not_printed_as_violations(client, scripted):
    """NEEDS_REVIEW must read as an unanswered question, not a finding against the pack."""
    scan = file_scan(client)
    html = html_of(client, scan["scan_id"])
    assert scan["assessment"]["needs_review"] > 0
    assert "NEEDS REVIEW" in html
    assert "questions the images could not settle, not violations" in html


def test_an_uncalibrated_report_says_no_measurement_was_possible(client, scripted):
    """The page must not leave a reader thinking the font checks were performed."""
    scan = file_scan(client)
    assert scan["calibration"]["calibrated"] is False
    html = html_of(client, scan["scan_id"])
    assert "No millimetre measurement was possible" in html
    assert "scale card" in html


def test_an_unreadable_scan_is_not_scored_on_paper(client):
    """A blank frame. The report must not print a zero, which reads as a judgement."""
    scan = file_scan(client)  # real engine, blank image
    assert scan["assessment"]["score"] is None
    html = html_of(client, scan["scan_id"])
    assert "Not scored" in html
    assert "No rule could be decided" in html


def test_the_disclaimer_is_on_every_report(client, scripted):
    scan = file_scan(client)
    html = html_of(client, scan["scan_id"])
    assert "decision support, not a legal determination" in html.lower()


def test_the_provenance_needed_to_reproduce_the_report_is_printed(client, scripted):
    scan = file_scan(client)
    html = html_of(client, scan["scan_id"])
    assert scan["ruleset_version"] in html
    assert scan["extractor_version"] in html
    assert scan["scan_id"] in html


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_an_override_is_printed_beside_the_machines_finding(client, scripted):
    """On paper too: both, never one replacing the other."""
    scan = file_scan(client)
    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        json={
            "status": "PASS",
            "reason": "Tax rider is printed on the reverse panel, verified on the pack.",
        },
    )
    html = html_of(client, scan["scan_id"])
    assert "Officer decision" in html
    assert "reverse panel" in html
    # The software's original verdict is still on the page.
    assert "FAIL" in html
    assert "The software found" in html


@pytest.mark.parametrize("scripted", [NO_TAX_RIDER], indirect=True)
def test_regenerating_a_report_reflects_the_current_record(client, scripted):
    scan = file_scan(client)
    first = client.post(f"{API}/scans/{scan['scan_id']}/report")
    assert first.status_code == 201

    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        json={"status": "PASS", "reason": "Verified on the reverse panel of the pack."},
    )
    client.post(f"{API}/scans/{scan['scan_id']}/report")

    payload = json.loads(client.get(f"{API}/scans/{scan['scan_id']}/report.json").content)
    finding = next(
        f for f in payload["scan"]["findings"] if f["rule_id"] == "MRP_INCLUSIVE_OF_TAXES"
    )
    assert finding["status"] == "PASS"
    assert finding["override"]["original_status"] == "FAIL"


def test_generating_a_report_is_audit_logged(client, scripted):
    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/report")
    entries = client.get(f"{API}/auth/audit", params={"entity_type": "scan"}).json()
    assert any(e["action"] == "REPORT_GENERATED" for e in entries)


def test_the_pdf_engine_reports_which_one_it_used():
    from app.reports import pdf

    assert pdf.available_engine() in ("weasyprint", "xhtml2pdf")


def test_a_font_that_can_print_a_rupee_sign_is_vendored():
    """The base-14 PDF fonts have no glyph at U+20B9.

    Without a vendored face, every MRP in a report prints as a tofu box — on a document
    whose subject is maximum retail price. This is the check that the face is actually
    there, before the slower one below that it reaches the page.
    """
    from fontTools.ttLib import TTFont

    from app.reports import pdf

    assert pdf.fonts_available(), "no report font is vendored; ₹ will not render"
    cmap = TTFont(pdf.FONTS / "DejaVuSans.ttf").getBestCmap()
    for codepoint, name in [
        (0x20B9, "RUPEE SIGN"),
        (0x00B2, "SUPERSCRIPT TWO"),  # cm² in every Rule 8 finding
        (0x2014, "EM DASH"),
        (0x201C, "LEFT DOUBLE QUOTATION MARK"),
    ]:
        assert codepoint in cmap, f"the report font has no {name}"


@pytest.mark.parametrize("scripted", [[*COMPLIANT_LINES, "MRP ₹45.00"]], indirect=True)
def test_the_rupee_sign_survives_into_the_pdf(client, scripted):
    """End to end, in the artefact that leaves the building.

    Asserting on the vendored font is not enough — the font also has to be selected by
    the stylesheet and embedded by whichever engine ran. Extracting the text back out
    of the PDF is the only check that all three happened.
    """
    from pypdf import PdfReader

    scan = file_scan(client)
    client.post(f"{API}/scans/{scan['scan_id']}/report")
    content = client.get(f"{API}/scans/{scan['scan_id']}/report.pdf").content

    reader = PdfReader(io.BytesIO(content))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "₹" in text, "the rupee sign did not reach the page"
    assert "�" not in text and "■" not in text, "a glyph fell back to tofu"


def test_a_report_renders_without_any_evidence_image(client, scripted, monkeypatch):
    """A missing evidence file must cost the illustrations, not the findings."""
    from app.services import storage

    scan = file_scan(client)

    def gone(_key):
        raise storage.StorageError("gone")

    monkeypatch.setattr(storage, "path_of", gone)
    response = client.post(f"{API}/scans/{scan['scan_id']}/report")
    assert response.status_code == 201
