"""What a scan looks like on the wire.

The response shapes here are not a neutral serialisation of the engine's output. They
are the same invariants the rule engine enforces, carried across the HTTP boundary and
made structural, so a client cannot present a result more confidently than the evidence
supports even by accident:

  * `score` never appears on its own. It lives inside `assessment`, which always carries
    the verdict and the coverage that qualifies it. There is no shape a client can bind
    to that yields a bare number.
  * Every finding carries `decided`. NEEDS_REVIEW and NA are false, so "is this settled"
    is one boolean rather than a status-string comparison each client reimplements.
  * Every finding carries an `evidence` object, present or absent. A FAIL with nothing
    behind it says so in `note` rather than serialising as a null the UI can skip.
  * Calibration is reported as its own object with an explicit `calibrated` flag. A
    millimetre figure without one is not a measurement.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Channel, FindingStatus, Severity, Verdict


class EvidenceOut(BaseModel):
    """What the finding was decided from, traced back to pixels where possible."""

    located: bool = Field(
        description="Whether the declaration this finding concerns was found at all."
    )
    field_key: str | None = None
    raw_text: str | None = Field(
        default=None, description="The text as read. Evidence, quoted — never judged."
    )
    confidence: float | None = Field(
        default=None, description="OCR confidence for the text above, 0-1."
    )
    bbox: list[float] | None = Field(default=None, description="[x, y, w, h] in source pixels.")
    image_id: str | None = None
    note: str | None = Field(
        default=None, description="Why there is no evidence, when located is false."
    )


class OverrideOut(BaseModel):
    """An officer's disagreement with the machine, recorded beside it.

    `status` on the finding is what stands. This object carries what the automated
    check originally decided, so the disagreement is visible rather than erased. A
    finding whose machine verdict has been silently replaced is not reviewable.
    """

    original_status: FindingStatus
    reason: str | None = None
    overridden_by_id: str | None = None
    overridden_at: datetime | None = None


class FindingOut(BaseModel):
    rule_id: str
    title: str
    citation: str
    status: FindingStatus
    severity: Severity
    message: str
    remediation: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    evidence: EvidenceOut
    decided: bool = Field(
        description=(
            "True only for PASS and FAIL. NEEDS_REVIEW and NA are open questions, not "
            "results, and must never be rendered as a settled outcome."
        )
    )
    override: OverrideOut | None = Field(
        default=None,
        description="Present when an officer changed this finding. Never replaces it.",
    )


class AssessmentOut(BaseModel):
    """The verdict, and the score that qualifies it — never the other way round.

    Two verdicts are reported, and both matter:

      * `verdict` / `score` are where the record **currently stands**, taking officer
        overrides into account. This is what an officer acts on.
      * `automated_verdict` / `automated_score` are what the software decided before
        any human touched it. They never change.

    Reporting only the first would let a series of overrides quietly rewrite what the
    system found; reporting only the second would leave a pack whose failures an
    officer has all resolved reading NON_COMPLIANT forever. The disagreement between
    the two is itself the useful signal, so neither is hidden.
    """

    verdict: Verdict = Field(description="Where the record stands now, after overrides.")
    score: float | None = Field(
        default=None,
        description=(
            "0-100 over the rules actually decided, or null when nothing could be "
            "decided. Meaningless without rules_decided/rules_applicable beside it."
        ),
    )
    automated_verdict: Verdict = Field(description="What the software decided. Immutable.")
    automated_score: float | None = None
    rules_decided: int
    rules_applicable: int
    failed: int
    needs_review: int
    overridden: int = Field(
        default=0, description="How many findings an officer has ruled on."
    )
    exemption_id: str | None = None


class CalibrationOut(BaseModel):
    """Whether any millimetre figure in this response means anything.

    Rule 8 is a physical measurement. Without a fiducial of known size in frame there
    is no scale, and every geometry finding is left for an officer. `calibrated` is the
    single flag a client must check before showing any mm value as measured.
    """

    calibrated: bool
    source: str
    mm_per_px: float | None = None
    confidence: float = 0.0
    detail: str = ""
    pdp_area_cm2: float | None = None
    panel_method: str = "not determined"


class FieldOut(BaseModel):
    """One extracted declaration: the evidence and the parsed fact, kept apart."""

    field_key: str
    raw_text: str | None = None
    parsed: dict[str, Any] | None = Field(
        default=None, description="The typed declaration the rules judged."
    )
    confidence: float
    bbox: list[float] | None = None
    image_id: str | None = None
    glyph_height_mm: float | None = None
    glyph_width_mm: float | None = None


class ImageOut(BaseModel):
    image_id: str
    kind: str
    filename: str | None = None
    width: int
    height: int
    blocks_read: int


class RetentionRequest(BaseModel):
    """The officer's answer to "Is a case still open on this scan?".

    A plain boolean, not a nullable one: there is no wire value for "no answer". Not
    answering means not calling this endpoint at all, and the scan stays not eligible.
    """

    case_open: bool = Field(
        description="True keeps the scan indefinitely. False starts the retention "
        "clock from now.",
    )


class DeleteScanRequest(BaseModel):
    """The optional note recorded with a manual soft-delete."""

    reason: str | None = Field(
        default=None,
        max_length=64,
        description="Why the scan is being removed. Kept in the audit trail.",
    )


class RetentionWindowRequest(BaseModel):
    """An administrator setting the auto-deletion window."""

    days: int = Field(
        ge=1,
        le=3650,
        description="Days after an officer records case_open = False before the scan "
        "becomes eligible for automatic deletion.",
    )


class RetentionWindowOut(BaseModel):
    days: int = Field(description="The auto-deletion window currently in force.")


class RetentionOut(BaseModel):
    """Where a scan stands with respect to deletion.

    `case_open` is `None` until an officer answers the retention question. That is not a
    default of False — a scan with no answer is never eligible for auto-deletion, and
    the UI must prompt for an answer rather than assume one.
    """

    case_open: bool | None = Field(
        description="True = a case is open (never auto-deleted). False = eligible after "
        "the window. None = not yet reviewed.",
    )
    decided_at: datetime | None = None
    decided_by_id: str | None = None
    eligible_for_deletion: bool = Field(
        description="Only ever true when case_open is False and the window has elapsed.",
    )
    eligible_on: datetime | None = Field(
        default=None,
        description="When it becomes eligible; null unless case_open is False.",
    )
    summary: str = Field(description="A sentence an officer can read.")


class ScanResultOut(BaseModel):
    scan_id: str
    product_id: str | None = None
    product_name: str | None = None
    channel: Channel
    scan_date: date
    created_at: datetime | None = None
    ruleset_version: str
    extractor_version: str
    revision: int = Field(
        default=1,
        description="Which reading this is. Above 1 means the photographs were edited.",
    )
    retention: RetentionOut
    # Set once the scan has been soft-deleted. The row and its evidence are kept for
    # the audit trail; a deleted scan is simply no longer part of a working listing.
    deleted_at: datetime | None = None
    deleted_reason: str | None = None
    assessment: AssessmentOut
    calibration: CalibrationOut
    findings: list[FindingOut]
    fields: list[FieldOut]
    images: list[ImageOut]
    notes: list[str] = Field(
        default_factory=list,
        description="What the scan could not do, in the officer's words.",
    )


class ScanSummaryOut(BaseModel):
    """A row in the repository listing.

    Carries the verdict and the coverage, never a bare score — a list view is exactly
    where a lone number would be skimmed as a grade.
    """

    scan_id: str
    product_id: str
    product_name: str | None = None
    scan_date: date
    created_at: datetime | None = None
    verdict: Verdict
    score: float | None = None
    rules_decided: int
    rules_applicable: int
    failed: int
    needs_review: int
    ruleset_version: str | None = None
    case_open: bool | None = Field(
        default=None,
        description="The officer's retention answer, or null if not yet reviewed.",
    )
    eligible_for_deletion: bool = False
    deleted: bool = Field(
        default=False,
        description="True when the scan has been soft-deleted (shown only when "
        "deleted scans are explicitly requested).",
    )


class ScanPageOut(BaseModel):
    total: int
    limit: int
    offset: int
    scans: list[ScanSummaryOut]


class ScanRevisionOut(BaseModel):
    """A reading of a scan that an image edit superseded.

    `snapshot` is the whole ScanResultOut as it stood — including any officer decisions
    recorded against the findings of that reading. An edit moves a result here; it does
    not discard it.
    """

    revision: int
    reason: str = Field(description="What made this reading stale.")
    detail: str | None = None
    superseded_at: datetime | None = None
    superseded_by_id: str | None = None
    snapshot: dict[str, Any]


class ReportOut(BaseModel):
    scan_id: str
    generated_at: datetime | None = None
    generated_by_id: str | None = None
    pdf_url: str
    json_url: str
    engine: str = Field(description="Which PDF engine rendered it.")


class RulesetOut(BaseModel):
    version: str
    effective_date: date
    description: str
    source: str
    rule_count: int


class HealthOut(BaseModel):
    status: str
    environment: str
    ocr_engine: str
    rulesets: list[str]
    database: str = Field(description="CURRENT, BEHIND, UNINITIALISED or UNREACHABLE.")
    database_detail: str = ""
