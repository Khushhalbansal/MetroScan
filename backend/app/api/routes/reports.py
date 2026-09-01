"""Generating and fetching a scan's compliance report."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

from app.api.deps import AnyOfficer, DbSession, WritableDb
from app.rules.loader import ruleset_by_version, ruleset_for_date
from app.schemas.scan import ReportOut
from app.services import audit, persistence, reporting, storage

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scans/{scan_id}/report", tags=["reports"])


def _load(db, scan_id: str):
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")
    try:
        ruleset = ruleset_by_version(scan.ruleset_version or "")
    except KeyError:
        log.warning(
            "Scan %s cites ruleset %r, which is no longer on disk; reporting against "
            "the set in force on its scan date.",
            scan.id, scan.ruleset_version,
        )
        ruleset = ruleset_for_date(scan.scan_date)
    return scan, ruleset


def _stored(db, scan_id: str, attribute: str, media_type: str, filename: str):
    scan, _ = _load(db, scan_id)
    report = scan.report
    if report is None or not getattr(report, attribute):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No report has been generated for this scan yet. "
            f"POST to /scans/{scan_id}/report first.",
        )
    try:
        path = storage.path_of(getattr(report, attribute))
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post(
    "",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate the compliance report for a scan",
)
def generate_report(scan_id: str, db: WritableDb, officer: AnyOfficer) -> ReportOut:
    """Render the PDF and JSON and store both.

    Re-generating replaces the stored files. That is deliberate: a report must reflect
    the record as it now stands, including any officer overrides made since the last
    one. The overrides themselves, and the software's original findings, are preserved
    in the scan and printed in the report, so nothing is lost by re-rendering.
    """
    scan, ruleset = _load(db, scan_id)
    try:
        report = reporting.generate(db, scan, ruleset, generated_by=officer)
    except reporting.pdf.PdfError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc

    audit.record(
        db,
        action="REPORT_GENERATED",
        entity_type="scan",
        entity_id=scan.id,
        actor=officer,
        after={"pdf_key": report.pdf_key, "json_key": report.json_key},
    )
    db.commit()
    return ReportOut(
        scan_id=scan.id,
        generated_at=report.updated_at,
        generated_by_id=report.generated_by_id,
        pdf_url=f"/api/v1/scans/{scan.id}/report.pdf",
        json_url=f"/api/v1/scans/{scan.id}/report.json",
        engine=reporting.pdf.available_engine(),
    )


@router.get(".pdf", summary="The report as a PDF", response_class=FileResponse)
def get_report_pdf(scan_id: str, db: DbSession, officer: AnyOfficer):
    return _stored(db, scan_id, "pdf_key", "application/pdf", f"compliance-{scan_id[:8]}.pdf")


@router.get(".json", summary="The report as JSON", response_class=FileResponse)
def get_report_json(scan_id: str, db: DbSession, officer: AnyOfficer):
    return _stored(
        db, scan_id, "json_key", "application/json", f"compliance-{scan_id[:8]}.json"
    )


@router.get(
    ".html",
    summary="The report as HTML, for review before printing",
    response_class=HTMLResponse,
)
def get_report_html(scan_id: str, db: DbSession, officer: AnyOfficer) -> HTMLResponse:
    """Rendered live rather than stored.

    Useful for checking a report without producing a filed artefact, and it is what the
    PDF is made from — so if the HTML looks right and the PDF does not, the fault is in
    the PDF engine rather than the report.
    """
    scan, ruleset = _load(db, scan_id)
    result = persistence.to_response(scan, ruleset)
    images = {
        image_id: reporting._thumbnail(png)
        for image_id, png in reporting._annotated_images(scan, result).items()
    }
    html = reporting.render.build_html(
        result,
        evidence_png=images,
        generated_by=officer.email,
        engine=reporting.pdf.available_engine(),
    )
    return HTMLResponse(html)
