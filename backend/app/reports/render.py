"""Build the report HTML from a stored scan.

The report is rendered from the same `ScanResultOut` the API returns, so paper and
screen are two views of one record rather than two computations that agree until they
do not.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.enums import FindingStatus
from app.reports import measure as measure_mod
from app.reports import pdf as pdf_mod
from app.rules.engine import PASS_THRESHOLD
from app.schemas.scan import ScanResultOut

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _macros():
    module = _env.get_template("measure.html").module
    return module.ruler, module.score_scale  # type: ignore[attr-defined]


def _data_uri(png: bytes) -> str:
    """Images are embedded rather than linked.

    A report is filed, emailed and printed. One whose evidence lives at a URL is one
    whose evidence disappears the moment it leaves this server — which is precisely
    when it is being used to justify something.
    """
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def build_html(
    scan: ScanResultOut,
    *,
    evidence_png: dict[str, bytes] | None = None,
    generated_by: str | None = None,
    engine: str = "",
) -> str:
    """Render the report. `evidence_png` maps image_id to annotated PNG bytes."""
    ruler, score_scale = _macros()
    evidence_png = evidence_png or {}

    findings: list[dict[str, Any]] = []
    for finding in scan.findings:
        row = finding.model_dump()
        # A ruler only where there is a measurement to draw. Rendering one for a
        # presence check would be inventing a reading.
        row["measure"] = measure_mod.from_finding(finding.detail or {}, finding.citation)
        findings.append(row)

    decided = [f for f in findings if f["status"] != FindingStatus.NA]
    not_applicable = [f for f in findings if f["status"] == FindingStatus.NA]

    # Failures first, then open questions, then passes: a reader scanning the first
    # page must meet the violations before the clean rules.
    order = {
        FindingStatus.FAIL: 0,
        FindingStatus.NEEDS_REVIEW: 1,
        FindingStatus.PASS: 2,
    }
    decided.sort(key=lambda f: (order.get(f["status"], 3), f["rule_id"]))

    images = [
        {
            "image_id": image.image_id,
            "kind": image.kind,
            "src": _data_uri(evidence_png[image.image_id]),
            "annotated": True,
        }
        for image in scan.images
        if image.image_id in evidence_png
    ]

    return _env.get_template("report.html").render(
        scan=scan.model_dump(),
        decided_findings=decided,
        na_findings=not_applicable,
        evidence_images=images,
        ruler=ruler,
        score_scale=score_scale,
        pass_threshold=PASS_THRESHOLD,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        generated_by=generated_by,
        engine=engine,
        # WeasyPrint loads the faces from @font-face. xhtml2pdf cannot — it fetches
        # the src to a temp file it then fails to reopen — so it gets the same faces
        # registered with reportlab instead. See app/reports/pdf.py.
        font_css=pdf_mod.font_css() if engine != "xhtml2pdf" else "",
    )
