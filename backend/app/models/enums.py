"""Domain enumerations shared by models, schemas and the rule engine."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    SENIOR_OFFICER = "SENIOR_OFFICER"
    FIELD_INSPECTOR = "FIELD_INSPECTOR"
    AUDITOR = "AUDITOR"
    MANUFACTURER = "MANUFACTURER"


class Channel(StrEnum):
    """Which rule profile applies. Rule 6(10) relaxes mfg date + USP for listings."""

    PHYSICAL = "PHYSICAL"
    ECOMMERCE = "ECOMMERCE"


class ScanStatus(StrEnum):
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    EVALUATING = "EVALUATING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ImageKind(StrEnum):
    FRONT = "FRONT"
    BACK = "BACK"
    SIDE = "SIDE"
    LISTING = "LISTING"
    EVIDENCE = "EVIDENCE"


class FindingStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


# Weight each severity contributes when a rule fails, used for the compliance score.
SEVERITY_WEIGHT: dict[Severity, int] = {
    Severity.CRITICAL: 10,
    Severity.MAJOR: 5,
    Severity.MINOR: 2,
}


class Verdict(StrEnum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    INCONCLUSIVE = "INCONCLUSIVE"


class CaseState(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    VIOLATION_CONFIRMED = "VIOLATION_CONFIRMED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    CLOSED = "CLOSED"


CASE_FLOW: dict[CaseState, tuple[CaseState, ...]] = {
    CaseState.DRAFT: (CaseState.UNDER_REVIEW,),
    CaseState.UNDER_REVIEW: (CaseState.VIOLATION_CONFIRMED, CaseState.CLOSED),
    CaseState.VIOLATION_CONFIRMED: (CaseState.NOTICE_ISSUED, CaseState.CLOSED),
    CaseState.NOTICE_ISSUED: (CaseState.CLOSED,),
    CaseState.CLOSED: (),
}


class FieldKey(StrEnum):
    """The mandatory declarations of Rule 6(1), plus supporting fields we extract."""

    MANUFACTURER_NAME = "manufacturer_name"
    MANUFACTURER_ADDRESS = "manufacturer_address"
    COMMON_NAME = "common_name"
    NET_QUANTITY = "net_quantity"
    MFG_DATE = "mfg_date"
    MRP = "mrp"
    CONSUMER_CARE_NAME = "consumer_care_name"
    CONSUMER_CARE_ADDRESS = "consumer_care_address"
    CONSUMER_CARE_PHONE = "consumer_care_phone"
    CONSUMER_CARE_EMAIL = "consumer_care_email"
    COUNTRY_OF_ORIGIN = "country_of_origin"
    UNIT_SALE_PRICE = "unit_sale_price"
    # supporting
    BATCH_NUMBER = "batch_number"
    FSSAI_NUMBER = "fssai_number"
    IMPORTER_NAME = "importer_name"
