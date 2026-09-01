"""ORM tables for the compliance bench."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin
from app.models.enums import (
    CaseState,
    Channel,
    FindingStatus,
    ImageKind,
    Role,
    ScanStatus,
    Severity,
    Verdict,
)


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.FIELD_INSPECTOR)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    is_imported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    created_by: Mapped[User] = relationship()
    scans: Mapped[list[Scan]] = relationship(back_populates="product", order_by="Scan.created_at")


class Scan(Base, TimestampMixin):
    """One compliance check of one product, against one ruleset version."""

    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel), default=Channel.PHYSICAL)
    status: Mapped[ScanStatus] = mapped_column(Enum(ScanStatus), default=ScanStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # provenance — every report must be reproducible
    ruleset_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_date: Mapped[date] = mapped_column(Date, default=date.today)

    # measurement context for the Rule 8 geometry checks
    mm_per_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    scale_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scale_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scale_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pdp_area_cm2: Mapped[float | None] = mapped_column(Float, nullable=True)
    panel_method: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Rule 26 exemption applied, if any — without it a stored scan cannot explain why
    # most of its rules came back NA.
    exemption_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # What the pipeline could not do, in the officer's words ("no text was read from
    # the submitted images"). Distinct from `notes` below, which the officer writes.
    # A stored scan without these reads as an empty result rather than a failed read.
    pipeline_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Which reading of this scan is current. Starts at 1 and increments each time the
    # image set is edited and the pipeline re-run; the superseded readings are in
    # scan_revisions.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # outcome
    compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[Verdict | None] = mapped_column(Enum(Verdict), nullable=True)

    # --- retention -------------------------------------------------------------
    #
    # The officer's answer to "Is a case still open on this scan?", and nothing else,
    # governs whether this scan is ever auto-deleted. The verdict does not: a COMPLIANT
    # scan flagged case_open = True (a repeat-inspection baseline, say) is retained the
    # same as any other.
    #
    #   None  — no answer has been given yet. NOT eligible for deletion. Silence is
    #           never treated as consent to delete.
    #   True  — a case is open. NEVER auto-deleted, at any age. Only a manual delete
    #           by an authorised role can remove it.
    #   False — no case is open. Eligible for auto-deletion once the configured window
    #           has passed *since case_open_decided_at* — the clock starts at the
    #           officer's decision, not at scan creation, so a scan under review for
    #           three weeks does not have only nine days left.
    case_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # When the current case_open answer was recorded. Reset every time the answer
    # changes, so setting it back to False after a reopen restarts the clock.
    case_open_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    case_open_decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # --- soft delete ---------------------------------------------------------------
    #
    # A deleted scan's row and its deletion event stay in the record permanently; only
    # the images and derived data are cleared. `deleted_at` set means the scan is gone
    # from every normal listing and its evidence is no longer on disk, but the audit
    # trail still shows it existed and when and why it was removed.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # field context
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    place_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    product: Mapped[Product] = relationship(back_populates="scans")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    case_open_decided_by: Mapped[User | None] = relationship(
        foreign_keys=[case_open_decided_by_id]
    )
    deleted_by: Mapped[User | None] = relationship(foreign_keys=[deleted_by_id])
    images: Mapped[list[ScanImage]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    findings: Mapped[list[Finding]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    revisions: Mapped[list[ScanRevision]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="ScanRevision.revision",
    )
    report: Mapped[Report | None] = relationship(
        back_populates="scan", uselist=False, cascade="all, delete-orphan"
    )
    case: Mapped[Case | None] = relationship(
        back_populates="scan", uselist=False, cascade="all, delete-orphan"
    )


class ScanImage(Base, TimestampMixin):
    __tablename__ = "scan_images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    kind: Mapped[ImageKind] = mapped_column(Enum(ImageKind), default=ImageKind.FRONT)
    storage_key: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    # raw OCR output kept for audit + re-evaluation without re-running OCR
    ocr_blocks: Mapped[list | None] = mapped_column(JSON, nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="images")


class ExtractedField(Base, TimestampMixin):
    """One mandatory declaration located on the package."""

    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("scan_id", "field_key", name="uq_scan_field"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    field_key: Mapped[str] = mapped_column(String(64), index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # normalised, type-appropriate value: {"amount": 45.0, "currency": "INR"} etc.
    normalized: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_image_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_images.id"), nullable=True
    )
    # [x, y, w, h] in pixels of the source image
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # measured glyph geometry, populated when mm_per_px is known
    glyph_height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    glyph_width_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_by: Mapped[str] = mapped_column(String(16), default="regex")  # regex | vlm | officer

    scan: Mapped[Scan] = relationship(back_populates="fields")


class Finding(Base, TimestampMixin):
    """The verdict of one rule against one scan."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    citation: Mapped[str] = mapped_column(String(120))
    status: Mapped[FindingStatus] = mapped_column(Enum(FindingStatus), index=True)
    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.MAJOR)
    message: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # structured detail the UI renders, e.g. the Measure: {"measured_mm":1.4,"required_mm":2.0}
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # officer override — the machine never has the last word
    original_status: Mapped[FindingStatus | None] = mapped_column(
        Enum(FindingStatus), nullable=True
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="findings")
    overridden_by: Mapped[User | None] = relationship()

    @property
    def is_overridden(self) -> bool:
        return self.original_status is not None


class ScanRevision(Base, TimestampMixin):
    """What a scan said before its image set was edited.

    Editing the photographs changes the evidence, so the findings have to be recomputed
    or they go stale — a violation still on screen that the new photograph disproves.
    But the earlier reading is not wrong to have made, and an officer who reopens the
    scan next year needs to see that it was made and on what.

    So each edit snapshots the whole prior result here before the re-run replaces it.
    This is the same principle as an override keeping `original_status` beside the new
    one, applied at the level of the whole scan: both readings survive, and which is
    current is never in doubt.

    The snapshot is JSON rather than archived rows on purpose. Copies of findings in
    the live tables would have to be excluded from every query that asks what a scan
    currently says, and the first query that forgot would quietly report a superseded
    violation as a standing one.
    """

    __tablename__ = "scan_revisions"
    __table_args__ = (UniqueConstraint("scan_id", "revision", name="uq_scan_revision"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    # 1 for the original reading, then 2, 3 ... Each row is the state *before* the
    # edit that superseded it.
    revision: Mapped[int] = mapped_column(Integer)
    # "image added" / "image removed" / "image replaced" — what made this stale.
    reason: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The whole prior result, in the shape the API returns.
    snapshot: Mapped[dict] = mapped_column(JSON)

    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="revisions")
    superseded_by: Mapped[User | None] = relationship()


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), unique=True, index=True)
    pdf_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docx_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    json_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="report")


class Case(Base, TimestampMixin):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), unique=True, index=True)
    state: Mapped[CaseState] = mapped_column(Enum(CaseState), default=CaseState.DRAFT, index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="case")
    assignee: Mapped[User | None] = relationship()


class RuleVersion(Base, TimestampMixin):
    """A dated, published ruleset. Scans record which version judged them."""

    __tablename__ = "rule_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    yaml_blob: Mapped[str] = mapped_column(Text)
    published_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class AppSetting(Base):
    """A single administrator-tunable value, keyed by name.

    Deliberately a key/value row rather than a column per setting: the only thing
    stored here today is the auto-deletion window, and a table that needs a migration
    every time an operator wants a knob is a table that ends up with hardcoded knobs.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class AuditLog(Base):
    """Append-only. Every state change an officer makes is recoverable from here."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    actor: Mapped[User | None] = relationship()
