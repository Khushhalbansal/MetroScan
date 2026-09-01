"""Generate and store a scan's report.

The PDF and the JSON are two renderings of one `ScanResultOut`, which is itself read
back out of the database. Nothing is recomputed on the way to paper — a report that
re-derives its own verdict is a second implementation of the rule engine, and the two
will disagree eventually.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import FindingStatus
from app.models.tables import Report, Scan, User
from app.reports import annotate, pdf, render
from app.rules.schema import RuleSet
from app.schemas.scan import ScanResultOut
from app.services import persistence, storage

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Decision support, not a legal determination. Findings marked NEEDS_REVIEW are "
    "questions the images could not settle, not violations. An officer must verify the "
    "package before any action is taken under the Legal Metrology Act, 2009."
)


def _annotated_images(scan: Scan, result: ScanResultOut) -> dict[str, bytes]:
    """One annotated PNG per image that a finding actually cited."""
    boxes_by_image: dict[str, list[tuple[list[float], FindingStatus, str]]] = {}
    for finding in result.findings:
        evidence = finding.evidence
        if not evidence.located or not evidence.bbox or not evidence.image_id:
            continue
        if finding.status is FindingStatus.NA:
            continue
        boxes_by_image.setdefault(evidence.image_id, []).append(
            (evidence.bbox, finding.status, finding.rule_id)
        )

    out: dict[str, bytes] = {}
    for image_row in scan.images:
        boxes = boxes_by_image.get(image_row.id)
        if not boxes:
            continue
        try:
            path = storage.path_of(image_row.storage_key)
        except storage.StorageError:
            # The report is still worth producing without its illustrations; losing the
            # findings because a file is missing would be the worse failure.
            log.warning("Evidence image %s is missing; report will omit it.", image_row.id)
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            log.warning("Evidence image %s could not be decoded; omitting.", image_row.id)
            continue
        out[image_row.id] = annotate.to_png(annotate.annotate(image, boxes))
    return out


def _thumbnail(png: bytes, max_edge: int = 900) -> bytes:
    """Downscale for the page. A 4000px photo embedded at full size makes a 30 MB PDF
    that nobody can email, which is how a report stops being used."""
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return png
    height, width = image.shape[:2]
    if max(height, width) <= max_edge:
        return png
    factor = max_edge / max(height, width)
    resized = cv2.resize(
        image, (int(width * factor), int(height * factor)), interpolation=cv2.INTER_AREA
    )
    return annotate.to_png(resized)


def json_payload(result: ScanResultOut, *, generated_by: str | None) -> dict:
    """The machine-readable report: the whole record, plus who produced it when."""
    return {
        "report": {
            "generated_at": datetime.now(UTC).isoformat(),
            "generated_by": generated_by,
            "disclaimer": DISCLAIMER,
            "format_version": 1,
        },
        "scan": result.model_dump(mode="json"),
    }


def generate(
    db: Session,
    scan: Scan,
    ruleset: RuleSet,
    *,
    generated_by: User | None = None,
) -> Report:
    """Render the PDF and JSON for one scan, store both, and record them."""
    result = persistence.to_response(scan, ruleset)
    engine = pdf.available_engine()

    images = {
        image_id: _thumbnail(png)
        for image_id, png in _annotated_images(scan, result).items()
    }
    html = render.build_html(
        result,
        evidence_png=images,
        generated_by=generated_by.email if generated_by else None,
        engine=engine,
    )
    rendered = pdf.render(html)

    pdf_key = storage.put_bytes(
        rendered.pdf, scan_id=scan.id, name="report.pdf"
    )
    json_key = storage.put_bytes(
        json.dumps(json_payload(result, generated_by=generated_by.email if generated_by else None),
                   indent=2, ensure_ascii=False).encode("utf-8"),
        scan_id=scan.id,
        name="report.json",
    )

    report = db.execute(select(Report).where(Report.scan_id == scan.id)).scalars().first()
    if report is None:
        report = Report(scan_id=scan.id)
        db.add(report)
    report.pdf_key = pdf_key
    report.json_key = json_key
    report.generated_by_id = generated_by.id if generated_by else None
    db.flush()

    log.info("Report for scan %s rendered with %s.", scan.id, rendered.engine)
    return report
