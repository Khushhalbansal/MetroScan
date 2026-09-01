"""Reseed data/bench.db with a believable demo set.

    ../.venv/Scripts/python.exe -m scripts.seed_demo          (run from backend/)

Destructive for scan data only: it clears scans/findings/images/etc. in place (the
schema and the user accounts are left alone) and files a fresh set through the real
`POST /scans` path so the shape is identical to production.

The set is chosen so the Overview reads as a real enforcement picture — a mix of
COMPLIANT, NON-COMPLIANT at varied severity, and a couple of INCONCLUSIVE — across
FOOD / BEVERAGE / SNACKS / PERSONAL CARE / HOUSEHOLD, spread over the last six weeks.
Two scans run through real OCR + scale detection so the Measure shows an actual
millimetre reading; the rest use a scripted engine for speed.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("RETENTION_SWEEP_ENABLED", "false")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.enums import Role  # noqa: E402
from app.models.tables import (  # noqa: E402
    AuditLog,
    Case,
    ExtractedField,
    Finding,
    Product,
    Report,
    Scan,
    ScanImage,
    ScanRevision,
    User,
)
from app.pipeline import engine_ocr, synth  # noqa: E402

API = "/api/v1"
ADMIN_EMAIL = "demo@metrology.gov.in"
ADMIN_PASSWORD = "vernier-brass-plumb-2026"  # local demo db only; data/ is gitignored

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


def without(*needles: str) -> list[str]:
    return [ln for ln in COMPLIANT_LINES if not any(n in ln for n in needles)]


def with_extra(*extra: str) -> list[str]:
    return [*COMPLIANT_LINES, *extra]


class Scripted:
    name = "scripted"

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def read(self, image, image_id=None):
        from app.pipeline.ocr import OcrBlock

        out = []
        for i, text in enumerate(self.lines):
            top = 20.0 + i * 40.0
            w = 12.0 * len(text)
            out.append(
                OcrBlock(
                    text=text,
                    polygon=[[20.0, top], [20.0 + w, top], [20.0 + w, top + 22.0], [20.0, top + 22.0]],
                    confidence=0.94,
                    image_id=image_id,
                )
            )
        return out


def png_of(spec) -> bytes:
    ok, buf = cv2.imencode(".png", synth.render(spec))
    assert ok
    return buf.tobytes()


def plain_png() -> bytes:
    """A blank label-shaped image with NO fiducial — so a scripted scan has no scale
    and Rule 8 lands at NEEDS_REVIEW (not a spurious FAIL against the synth card)."""
    import numpy as np

    ok, buf = cv2.imencode(".png", np.full((1200, 900, 3), 246, np.uint8))
    assert ok
    return buf.tobytes()


PLAIN_PNG = None  # filled in main()

# rule ids an officer routinely resolves with the pack in hand — overridden to PASS on
# the packs that are meant to read as clean.
OFFICER_CLEARS = (
    "NO_MISLEADING_DECLARATION",
    "FONT_HEIGHT_NET_QUANTITY",
    "FONT_HEIGHT_MINIMUM",
    "FONT_WIDTH_RATIO",
)

# name, category, mode, days_ago
#   mode: "compliant" | ("scripted", lines) | "real_compliant" | "real_undersized" | "sparse"
PLAN = [
    ("Sunrise Roasted Chana Masala 200 g", "FOOD", "real_compliant", 38),
    ("Himalaya Neem & Turmeric Face Wash 150 ml", "PERSONAL CARE", "compliant", 31),
    ("Tata Copper+ Packaged Water 1 L", "BEVERAGE", "compliant", 22),
    ("Aashirvaad Whole Wheat Atta 1 kg", "FOOD", "compliant", 9),
    ("Crax Corn Rings — Tomato 55 g", "SNACKS", ("scripted", without("inclusive of all taxes")), 34),
    ("Let's Try Aloo Bhujia 400 g", "SNACKS", ("scripted", with_extra("MRP Rs. 52.00")), 27),
    ("GlowWell Vitamin C Face Serum 30 ml", "PERSONAL CARE", ("scripted", without("care@sunrisefoods.in")), 19),
    ("SparkClean Dishwash Gel 500 ml", "HOUSEHOLD", ("scripted", without("MRP Rs. 45.00", "inclusive of all taxes", "per g")), 14),
    ("FreshHome Floor Cleaner — Citrus 1 L", "HOUSEHOLD", ("scripted", without("Mfd. 03/2026")), 6),
    ("Nutri Millet Puffs 90 g", "FOOD", "real_undersized", 4),
    ("Frooti Mango Drink 250 ml", "BEVERAGE", "sparse", 12),
    ("Yoga Bar Protein Oats — Cocoa 350 g", "FOOD", "sparse", 3),
    # a re-inspection: the same non-compliant pack, checked again more recently
    ("Crax Corn Rings — Tomato 55 g", "SNACKS", ("scripted", without("inclusive of all taxes")), 2),
]


def wipe(db) -> None:
    for model in (
        AuditLog, Report, Case, ScanRevision, Finding, ExtractedField, ScanImage, Scan, Product,
    ):
        if model is AuditLog:
            db.execute(delete(AuditLog).where(AuditLog.entity_type.in_(("scan", "product"))))
        else:
            db.execute(delete(model))
    db.commit()


def ensure_admin(db) -> None:
    if db.query(User).filter(User.email == ADMIN_EMAIL).first():
        return
    db.add(
        User(
            email=ADMIN_EMAIL,
            full_name="Demo Controller",
            password_hash=hash_password(ADMIN_PASSWORD),
            role=Role.ADMIN,
            jurisdiction="Nashik",
            is_active=True,
        )
    )
    db.commit()


def file_one(client: TestClient, real_engine, name: str, category: str, mode, days_ago: int):
    if mode == "real_compliant":
        engine_ocr.set_engine(real_engine)
        img = png_of(synth.compliant_label())
    elif mode == "real_undersized":
        engine_ocr.set_engine(real_engine)
        img = png_of(synth.label_with({"undersized_net_quantity"}))
    elif mode == "compliant":
        engine_ocr.set_engine(Scripted(COMPLIANT_LINES))
        img = PLAIN_PNG
    elif mode == "sparse":
        engine_ocr.set_engine(Scripted(["Frooti", "Mango Drink"]))
        img = PLAIN_PNG
    else:  # ("scripted", lines)
        engine_ocr.set_engine(Scripted(mode[1]))
        img = PLAIN_PNG

    when = date.today() - timedelta(days=days_ago)
    r = client.post(
        f"{API}/scans",
        files=[("images", ("front.png", img, "image/png"))],
        data={"product_name": name, "category": category, "scan_date": when.isoformat()},
    )
    assert r.status_code == 201, f"{name}: {r.status_code} {r.text[:300]}"
    body = r.json()
    a = body.get("assessment") or {}
    return body["scan_id"], a.get("verdict"), a.get("score"), body.get("findings", [])


def clear_findings(client: TestClient, scan_id: str, findings: list[dict], mode) -> None:
    """Record the officer decisions a clean pack would really get: 'no misleading
    claim' everywhere, and — on the packs meant to read as compliant — the Rule 8
    height checks confirmed against the pack with a rule."""
    to_clear = OFFICER_CLEARS if mode in ("compliant", "real_compliant") else (
        "NO_MISLEADING_DECLARATION",
    )
    reason = {
        "NO_MISLEADING_DECLARATION": "Reviewed the pack; no misleading or unverifiable claim.",
        "FONT_HEIGHT_NET_QUANTITY": "Net-quantity numerals measured against a rule; meet Rule 8.",
        "FONT_HEIGHT_MINIMUM": "Declaration lettering measured against a rule; meets the minimum.",
        "FONT_WIDTH_RATIO": "Letterform width checked against the pack; within the one-third ratio.",
    }
    for f in findings:
        rid = f.get("rule_id")
        if rid in to_clear and f.get("status") in ("FAIL", "NEEDS_REVIEW"):
            client.post(
                f"{API}/scans/{scan_id}/findings/{rid}:override",
                json={"status": "PASS", "reason": reason[rid]},
            )


def backdate(db, scan_id: str, days_ago: int) -> None:
    scan = db.get(Scan, scan_id)
    ts = datetime.now(UTC) - timedelta(days=days_ago, hours=days_ago % 5)
    scan.created_at = ts
    scan.scan_date = ts.date()
    db.commit()


def main() -> int:
    global PLAIN_PNG
    app = create_app()
    real_engine = engine_ocr.get_engine()
    if real_engine.name == "stub":
        print("real OCR weights unavailable — the two Measure scans will be scripted-quality")
    PLAIN_PNG = plain_png()

    db = SessionLocal()
    try:
        wipe(db)
        ensure_admin(db)
    finally:
        db.close()

    with TestClient(app) as client:
        tok = client.post(
            f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {tok}"

        filed = []
        for name, category, mode, days_ago in PLAN:
            scan_id, verdict, score, findings = file_one(
                client, real_engine, name, category, mode, days_ago
            )
            clear_findings(client, scan_id, findings, mode)
            final = client.get(f"{API}/scans/{scan_id}").json().get("assessment") or {}
            filed.append(
                (scan_id, days_ago, name, final.get("verdict"), final.get("score"))
            )
            print(f"  {final.get('verdict') or '?':14s} "
                  f"{final.get('score') if final.get('score') is not None else '—'!s:>6}  {name}")

    # The stored Scan.verdict is the automated result; the dashboard reads it directly
    # and never recomputes. For demo data we want the Overview to reflect where the
    # record actually stands after the officer decisions above, so write the standing
    # verdict/score back onto the row.
    from app.models.enums import Verdict  # noqa: PLC0415

    db = SessionLocal()
    try:
        for scan_id, days_ago, _name, verdict, score in filed:
            backdate(db, scan_id, days_ago)
            s = db.get(Scan, scan_id)
            if verdict:
                s.verdict = Verdict(verdict)
            s.compliance_score = score
        db.commit()
        counts: dict[str, int] = {}
        for s in db.query(Scan).all():
            counts[str(s.verdict)] = counts.get(str(s.verdict), 0) + 1
    finally:
        db.close()

    engine_ocr._engine = real_engine
    print(f"\n{len(filed)} scans filed. verdict mix: {counts}")
    print(f"admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
