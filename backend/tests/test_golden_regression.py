"""Real photographs of real packs, run through the actual pipeline.

Two officer-supplied submissions, kept as permanent fixtures so the bugs they exposed
cannot come back:

  golden/lets_try/          a namkeen packet (Earth Crust Pvt Ltd), 2 images. A PIN
                            hyphen-glued to the state name, and MRP / MFG-date printed
                            in a flattened price table.
  golden/crax_masala_punch/ Crax Masala Punch (DFM Foods Ltd), 5 images. Company name
                            and address split across panels, a per-gram unit price
                            colliding with the MRP, and a tax rider broken mid-word.
  golden/oats_cereal/       Yoga Bar High Protein Oats (Sproutlife Foods), 4 images. A
                            printed-form back panel — static labels ("MRP ₹", "USP ₹",
                            "Date of Mfg.:") with values ink-stamped in a separate
                            column. The ₹ stamped as "MRP3", so the price read as ₹3;
                            the date and unit price were stamped over two lines each
                            and OCR merged them to nothing.

These assert the finding *statuses* an officer should see. NEEDS_REVIEW is an
acceptable outcome for a genuinely marginal read; a wrong FAIL is not, so every set
also declares which rules may legitimately fail and nothing else is allowed to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("cv2", reason="OpenCV is required for the golden regression run")

import cv2

from app.models.enums import FindingStatus
from app.pipeline.engine_ocr import get_engine
from app.pipeline.runner import ScanInput, run_scan

pytestmark = pytest.mark.slow

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def ocr():
    engine = get_engine()
    if engine.name == "stub":
        pytest.skip("OCR weights unavailable")
    return engine


def _run(folder: str):
    suffixes = {".jpeg", ".jpg", ".png"}
    paths = sorted(p for p in (GOLDEN / folder).iterdir() if p.suffix.lower() in suffixes)
    assert paths, f"no fixture images in {folder}"
    inputs = [
        ScanInput(image=cv2.imread(str(p)), image_id=f"img{i}", kind="FRONT" if i == 0 else "SIDE")
        for i, p in enumerate(paths)
    ]
    return run_scan(inputs)


def _statuses(outcome) -> dict[str, FindingStatus]:
    return {f.rule_id: f.status for f in outcome.findings}


# --------------------------------------------------------------------- lets_try

# rule_id -> the status it must have, or a set of acceptable statuses.
LETS_TRY_EXPECTED: dict[str, object] = {
    "MANUFACTURER_NAME_PRESENT": FindingStatus.PASS,
    "MANUFACTURER_ADDRESS_PRESENT": FindingStatus.PASS,
    # bug 1: the PIN is "...Haryana-131029" — hyphen-attached, no space.
    "MANUFACTURER_ADDRESS_COMPLETE": FindingStatus.PASS,
    # bug 2 / 3: MRP and the MFD date are printed in a flattened table. They were read,
    # so they must not hard-FAIL as "not on the submitted images".
    "MFG_DATE_PRESENT": FindingStatus.PASS,
    "MRP_PRESENT": {FindingStatus.PASS, FindingStatus.NEEDS_REVIEW},
    "MRP_SINGLE_VALUE": FindingStatus.PASS,
    "NET_QUANTITY_PRESENT": FindingStatus.PASS,
    "NET_QUANTITY_UNIT_VALID": FindingStatus.PASS,
    "CONSUMER_CARE_COMPLETE": FindingStatus.PASS,
    "UNIT_SALE_PRICE_PRESENT": FindingStatus.PASS,
}
# This pack, photographed without a scale card, should raise no hard failure at all.
LETS_TRY_ALLOWED_FAILS: set[str] = set()


# ------------------------------------------------------------ crax_masala_punch

CRAX_EXPECTED: dict[str, object] = {
    # bug 4: "DFM Foods Limited, 149, First Floor, Kilokari, Ring Road, Ashram, New
    # Delhi-110014" is printed on two panels; neither the name nor the address matched.
    "MANUFACTURER_NAME_PRESENT": FindingStatus.PASS,
    "MANUFACTURER_ADDRESS_PRESENT": FindingStatus.PASS,
    "MANUFACTURER_ADDRESS_COMPLETE": FindingStatus.PASS,
    # bug 5: name + address were reported missing though the phone from the same
    # paragraph was read fine.
    "CONSUMER_CARE_COMPLETE": FindingStatus.PASS,
    # bug 6: "inclusive of all taxes" sits a line below the price and is OCR-split.
    "MRP_INCLUSIVE_OF_TAXES": FindingStatus.PASS,
    # bug 7: "Rs.0.55/g" is a unit price, not a second MRP.
    "MRP_SINGLE_VALUE": FindingStatus.PASS,
    # bug 8: printed unit price ₹0.55/g agrees with 47.00 / 85 g.
    "UNIT_SALE_PRICE_PRESENT": FindingStatus.PASS,
    "MFG_DATE_PRESENT": FindingStatus.PASS,
    "NET_QUANTITY_PRESENT": FindingStatus.PASS,
    "NET_QUANTITY_UNIT_VALID": FindingStatus.PASS,
}
# DECLARATIONS_GROUPED is a real Rule 6(2) call for this pack — the declarations
# genuinely sit on several separate panels. It is left to fail on purpose.
CRAX_ALLOWED_FAILS = {"DECLARATIONS_GROUPED"}


# ---------------------------------------------------------------- oats_cereal

OATS_EXPECTED: dict[str, object] = {
    # The ₹ on "MRP ₹" was stamped as a "3" glued to the label ("MRP3:"), so the price
    # read as ₹3 and the row's own "RS." marking was ignored. The real figure, 229.00,
    # and the marking are both on the label's line.
    "MRP_PRESENT": FindingStatus.PASS,
    "MRP_CURRENCY_MARKED": FindingStatus.PASS,
    "MRP_SINGLE_VALUE": FindingStatus.PASS,
    "MRP_INCLUSIVE_OF_TAXES": FindingStatus.PASS,
    # "Date of Mfg.:" is a printed-form label; its ink stamp ("30/10/25", OCR'd as
    # "0TA301025007:38") sits in a value column knocked out of alignment by the tilt
    # of the shot. It is recovered by geometry — the nearest block to the right of the
    # heading whose digits parse as a real DD/MM/YY — so this now reads PASS, not just
    # NEEDS_REVIEW.
    "MFG_DATE_PRESENT": FindingStatus.PASS,
    # The per-gram unit price on this pack is genuinely mangled by OCR ("0.70" merged
    # into the MRP block, "/g" lost). Present label, unreadable value — an officer's
    # call. PASS allowed for the day OCR reads the stamp.
    "UNIT_SALE_PRICE_PRESENT": {FindingStatus.NEEDS_REVIEW, FindingStatus.PASS},
    "MANUFACTURER_NAME_PRESENT": FindingStatus.PASS,
    "MANUFACTURER_ADDRESS_PRESENT": FindingStatus.PASS,
    "MANUFACTURER_ADDRESS_COMPLETE": FindingStatus.PASS,
    "NET_QUANTITY_PRESENT": FindingStatus.PASS,
    "NET_QUANTITY_UNIT_VALID": FindingStatus.PASS,
    "CONSUMER_CARE_COMPLETE": FindingStatus.PASS,
}
# Photographed without a scale card and with a legible declarations panel — nothing on
# this pack should hard-fail.
OATS_ALLOWED_FAILS: set[str] = set()


@pytest.fixture(scope="module")
def lets_try(ocr):
    return _run("lets_try")


@pytest.fixture(scope="module")
def crax(ocr):
    return _run("crax_masala_punch")


@pytest.fixture(scope="module")
def oats(ocr):
    return _run("oats_cereal")


@pytest.mark.parametrize("rule_id, expected", list(LETS_TRY_EXPECTED.items()))
def test_lets_try_findings(lets_try, rule_id, expected):
    got = _statuses(lets_try)[rule_id]
    allowed = expected if isinstance(expected, set) else {expected}
    assert got in allowed, f"{rule_id}: expected {allowed}, got {got}"


def test_lets_try_raises_no_unexpected_failure(lets_try):
    failed = {r for r, s in _statuses(lets_try).items() if s is FindingStatus.FAIL}
    unexpected = failed - LETS_TRY_ALLOWED_FAILS
    assert not unexpected, f"unexpected FAIL(s): {unexpected}"


@pytest.mark.parametrize("rule_id, expected", list(CRAX_EXPECTED.items()))
def test_crax_findings(crax, rule_id, expected):
    got = _statuses(crax)[rule_id]
    allowed = expected if isinstance(expected, set) else {expected}
    assert got in allowed, f"{rule_id}: expected {allowed}, got {got}"


def test_crax_raises_no_unexpected_failure(crax):
    failed = {r for r, s in _statuses(crax).items() if s is FindingStatus.FAIL}
    unexpected = failed - CRAX_ALLOWED_FAILS
    assert not unexpected, f"unexpected FAIL(s): {unexpected}"


@pytest.mark.parametrize("rule_id, expected", list(OATS_EXPECTED.items()))
def test_oats_findings(oats, rule_id, expected):
    got = _statuses(oats)[rule_id]
    allowed = expected if isinstance(expected, set) else {expected}
    assert got in allowed, f"{rule_id}: expected {allowed}, got {got}"


def test_oats_raises_no_unexpected_failure(oats):
    failed = {r for r, s in _statuses(oats).items() if s is FindingStatus.FAIL}
    unexpected = failed - OATS_ALLOWED_FAILS
    assert not unexpected, f"unexpected FAIL(s): {unexpected}"
