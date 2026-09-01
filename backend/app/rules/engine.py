"""The rule engine.

Each check kind is a small function registered in CHECKS. Adding a rule usually means
adding YAML, not Python; adding a *kind* of reasoning means adding one function here.

Two principles run through every check:

  * Never fail on an unmeasurable input. If the scale is unknown, or the text was read
    with low confidence, the finding is NEEDS_REVIEW and goes to an officer. The system
    is decision support, not a determination.
  * Permissible error. Geometry comparisons carry a measurement tolerance, because a
    height recovered from a photograph is an estimate, not a callipered reading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from app.models.enums import SEVERITY_WEIGHT, FindingStatus, Severity, Verdict
from app.rules import units
from app.rules.schema import (
    Exemption,
    FieldValue,
    FindingResult,
    Rule,
    RuleSet,
    ScanContext,
)

# Below this OCR confidence a declaration is present but not trustworthy.
CONFIDENCE_FLOOR = 0.55
# A completeness check asks a negative question — "is a required part *not* there?".
# Answering it against anything less than a clean read invites failing a pack for a
# part OCR simply lost. Above this confidence the read is trusted enough to call a
# part genuinely absent; between here and CONFIDENCE_FLOOR the part is shown but the
# question goes to an officer. Set just under a clean read of a real pack (~0.88).
LEGIBLE_CONFIDENCE = 0.85
# Geometry is judged with a 10% measurement tolerance; inside it, an officer decides.
GEOMETRY_TOLERANCE = 0.10
# A scan whose verdict is COMPLIANT must score at least this.
PASS_THRESHOLD = 85.0

CheckFn = Callable[[Rule, ScanContext, RuleSet], FindingResult]
CHECKS: dict[str, CheckFn] = {}


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[name] = fn
        return fn

    return register


# --------------------------------------------------------------------------- helpers


def _result(
    rule: Rule,
    status: FindingStatus,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
    evidence: FieldValue | None = None,
) -> FindingResult:
    return FindingResult(
        rule_id=rule.id,
        title=rule.title,
        citation=rule.citation,
        status=status,
        severity=rule.severity,
        message=message,
        remediation=rule.remediation if status is FindingStatus.FAIL else None,
        detail=detail or {},
        evidence_bbox=evidence.bbox if evidence else None,
        evidence_image_id=evidence.image_id if evidence else None,
    )


def _passed(rule: Rule, message: str, **kw: Any) -> FindingResult:
    return _result(rule, FindingStatus.PASS, message, **kw)


def _failed(rule: Rule, message: str | None = None, **kw: Any) -> FindingResult:
    return _result(rule, FindingStatus.FAIL, message or rule.message_fail, **kw)


def _review(rule: Rule, message: str, **kw: Any) -> FindingResult:
    return _result(rule, FindingStatus.NEEDS_REVIEW, message, **kw)


def _not_applicable(rule: Rule, message: str) -> FindingResult:
    return _result(rule, FindingStatus.NA, message)


def _label(key: str) -> str:
    return key.replace("_", " ")


UNREADABLE = (
    "The label could not be read well enough to say whether this declaration is "
    "present. Re-photograph the pack in even light with the declaration panel in "
    "full view."
)


def _absent(rule: Rule, ctx: ScanContext, message: str | None = None, **kw: Any) -> FindingResult:
    """Report a declaration that was not found.

    Only a scan that actually read the label may call the declaration missing; one
    that read nothing must hand the question to an officer instead of inventing a
    violation. See ScanContext.can_assert_absence.
    """
    if not ctx.can_assert_absence:
        return _review(rule, UNREADABLE, detail={"reason": "unreadable"})
    return _failed(rule, message, **kw)


def _num(value: Any) -> float | None:
    """OCR-derived values reach us as whatever the extractor managed. Never trust the type."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- presence


@check("presence")
def check_presence(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    value = ctx.fields.get(rule.field_key or "")
    if value is None or not value.present:
        return _absent(rule, ctx)
    if value.confidence < CONFIDENCE_FLOOR:
        return _review(
            rule,
            f"Read “{value.raw_text}” with {value.confidence:.0%} confidence. "
            "Confirm this declaration against the package.",
            detail={"confidence": value.confidence, "raw_text": value.raw_text},
            evidence=value,
        )
    return _passed(rule, f"Declared as “{value.raw_text}”.", evidence=value)


@check("any_present")
def check_any_present(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    found = [k for k in rule.field_keys if ctx.get(k)]
    if not found:
        return _absent(rule, ctx)
    return _passed(
        rule,
        f"Found {', '.join(_label(k) for k in found)}.",
        detail={"found": found},
        evidence=ctx.get(found[0]),
    )


@check("all_present")
def check_all_present(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    present = [k for k in rule.field_keys if ctx.get(k)]
    missing = [k for k in rule.field_keys if not ctx.get(k)]
    if not missing:
        return _passed(rule, "All required parts are declared.", detail={"missing": []})

    # Some parts are here, but the weakest of them was read below a clean-read
    # confidence. On a block that OCR handled that badly, a part being absent from the
    # text is as likely a dropped read as a real omission — an officer's call.
    if present and min(ctx.fields[k].confidence for k in present) < LEGIBLE_CONFIDENCE:
        return _review(
            rule,
            f"{rule.message_fail} Read {', '.join(_label(k) for k in present)}; "
            f"could not confirm {', '.join(_label(k) for k in missing)}. "
            "The contact looks present but was not read cleanly — check the package.",
            detail={"missing": missing, "present": present},
        )
    return _absent(
        rule,
        ctx,
        f"{rule.message_fail} Missing: {', '.join(_label(k) for k in missing)}.",
        detail={"missing": missing},
    )


@check("attribute")
def check_attribute(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    r"""Require named attributes of the parsed declaration to be present.

    This replaces `format`, `normalized_present` and `mfg_date_format`, all of which
    re-derived facts the extractor had already parsed. Every one of them eventually
    disagreed with the extractor on real OCR output, and each disagreement condemned a
    compliant pack: `\b\d{6}\b` finds no PIN in "Maharashtra422010", `\bRs\.?\b` finds
    no marking in "MRPRs.45.00". Parsing happens once, in the extractor; a rule names
    the attribute it needs and the loader checks that attribute exists.
    """
    value = ctx.get(rule.field_key or "")
    if value is None:
        return _not_applicable(rule, "The declaration this rule inspects was not found.")

    missing = [name for name in rule.attributes if not value.attribute(name)]
    if not missing:
        shown = ", ".join(
            f"{_label(name)} “{value.attribute(name)}”" for name in rule.attributes
        )
        return _passed(rule, f"Read {shown}.", evidence=value)

    # The declaration is there but a required part of it did not parse. That is as
    # likely a bad read as a bad label, so anything short of a clean read of the
    # declaration goes to an officer rather than becoming a violation.
    if value.confidence < LEGIBLE_CONFIDENCE:
        return _review(
            rule,
            f"Could not read {', '.join(_label(m) for m in missing)} from "
            f"“{value.raw_text}”, which was read with {value.confidence:.0%} "
            "confidence. Confirm against the package.",
            detail={"missing_attributes": missing},
            evidence=value,
        )
    # An attribute is a part of a declaration, so its absence is a negative claim about
    # the label and needs the same support as a missing declaration. A scan that read
    # two blocks off one corner of a pack cannot testify that the tax rider is not
    # printed further down, or that the address carries no PIN.
    return _absent(
        rule,
        ctx,
        f"{rule.message_fail} Read: “{value.raw_text}”.",
        detail={"missing_attributes": missing},
        evidence=value,
    )


# --------------------------------------------------------------------------- semantics


@check("net_quantity_unit")
def check_net_quantity_unit(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    value = ctx.get(rule.field_key or "")
    if value is None:
        return _not_applicable(rule, "No net quantity declaration to check.")
    unit = value.attribute("unit")
    canonical = units.canonical(unit)
    if canonical is None:
        return _failed(
            rule,
            f"{rule.message_fail} Read the unit as “{unit or value.raw_text}”.",
            detail={"unit": unit},
            evidence=value,
        )
    basis = units.basis_of(canonical)
    return _passed(
        rule,
        f"Declared in {canonical}, a standard unit of {str(basis).lower()}.",
        detail={"unit": canonical, "basis": str(basis)},
        evidence=value,
    )


@check("mrp_single_value")
def check_mrp_single_value(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    value = ctx.get(rule.field_key or "")
    if value is None:
        return _not_applicable(rule, "No price declaration to check.")
    prices = [p for p in map(_num, value.attribute("all_amounts") or ()) if p is not None]
    distinct = sorted({round(p, 2) for p in prices})
    if len(distinct) > 1:
        shown = ", ".join(f"₹{p:.2f}" for p in distinct)
        return _failed(
            rule,
            f"{rule.message_fail} Found {shown}.",
            detail={"amounts": distinct},
            evidence=value,
        )
    only = f"₹{distinct[0]:.2f}" if distinct else value.raw_text
    return _passed(rule, f"A single price is declared: {only}.", evidence=value)


@check("unit_sale_price")
def check_unit_sale_price(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    usp = ctx.get(rule.field_key or "")
    mrp = ctx.get("mrp")
    net = ctx.get("net_quantity")

    # Rule 6(11) does not require a USP where it would equal the retail sale price,
    # which is the case for a single-unit pack of one gram, one millilitre or one piece.
    if net is not None:
        qty = _num(net.attribute("value"))
        unit = units.canonical(net.attribute("unit"))
        if qty is not None and unit in {"g", "ml", "pc", "n", "u"} and qty == 1:
            return _not_applicable(
                rule,
                "Unit sale price equals the retail sale price for this pack, "
                "so it is not required.",
            )
    if usp is None:
        return _absent(rule, ctx)

    # The label is on the pack but the extractor recovered no figure from it — a
    # stamped value the OCR could not read. That is an officer's call, the same as a
    # weakly-read declaration: never a pass, never "not declared".
    if _num(usp.attribute("amount")) is None:
        return _review(
            rule,
            "A unit sale price label is printed on the pack, but its value could not "
            "be read. Confirm the printed unit price against the pack.",
            detail={"reason": "unreadable"},
            evidence=usp,
        )

    if mrp and net:
        expected = _expected_unit_price(mrp, net)
        declared = _num(usp.attribute("amount"))
        if expected and declared is not None:
            # Two independent sources of difference, so they add rather than compete:
            # a printed price is quantised to paise (₹0.225 can only be shown as ₹0.23,
            # half a paisa out), and the declaration itself carries a 2% tolerance.
            # Taking the larger of the two would fail every correctly-rounded small
            # unit price by a fraction of a paisa.
            allowed = 0.005 + expected * 0.02
            if abs(declared - expected) > allowed:
                # The cross-check is only as sound as the two figures behind it. A net
                # quantity read weakly, or with no "Net Qty" label to anchor it, is as
                # likely to be a nutrition-panel number that bled in as a real
                # disagreement — so the mismatch goes to an officer, not straight to a
                # violation against the printed price.
                shaky = (
                    net.confidence < CONFIDENCE_FLOOR
                    or bool(net.attribute("unlabelled"))
                    or mrp.confidence < CONFIDENCE_FLOOR
                )
                if shaky:
                    return _review(
                        rule,
                        f"The declared unit sale price of ₹{declared:,.2f} does not match "
                        f"₹{expected:,.3f} implied by the MRP and net quantity, but the "
                        "net quantity was read too weakly to rely on the comparison. "
                        "Check the printed unit price against the pack.",
                        detail={"declared": declared, "computed": round(expected, 4)},
                        evidence=usp,
                    )
                return _failed(
                    rule,
                    f"The unit sale price of ₹{declared:,.2f} does not agree with the "
                    f"MRP and net quantity, which give ₹{expected:,.3f}.",
                    detail={"declared": declared, "computed": round(expected, 4)},
                    evidence=usp,
                )
    return _passed(rule, f"Declared as “{usp.raw_text}”.", evidence=usp)


def _expected_unit_price(mrp: FieldValue, net: FieldValue) -> float | None:
    """Unit price implied by MRP and net quantity, in the unit the pack should quote."""
    amount = _num(mrp.attribute("amount"))
    qty = _num(net.attribute("value"))
    unit = units.canonical(net.attribute("unit"))
    if amount is None or not qty or unit is None:
        return None
    base = units.to_base(qty, unit)
    if not base:
        return None
    per_base = amount / base
    # Packs of a kilogram or a litre and above quote per kg / per l.
    if unit in {"kg", "l", "ltr"} or base >= 1000:
        return per_base * 1000
    return per_base


@check("semantic_flag")
def check_semantic_flag(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    flag = rule.flag or ""
    if flag not in ctx.semantic_flags:
        return _review(
            rule,
            "This package was not assessed for misleading claims. Review the label directly.",
        )
    if ctx.semantic_flags[flag]:
        detail = ctx.semantic_flags.get(f"{flag}_detail")
        extra = f" {detail}" if isinstance(detail, str) else ""
        return _failed(rule, f"{rule.message_fail}{extra}")
    return _passed(rule, "No misleading or unverifiable claim was identified.")


@check("legibility")
def check_legibility(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    # "No declaration was read badly" is vacuously true when no declaration was read
    # at all, and would report a lens-cap photograph as perfectly legible.
    if not ctx.fields:
        return _review(
            rule,
            "No declaration was read from this scan, so legibility could not be "
            "assessed. Re-photograph the pack with the declaration panel in full view.",
            detail={"reason": "nothing_read"},
        )

    weak = {
        k: v.confidence
        for k, v in ctx.fields.items()
        if v.present and v.confidence < CONFIDENCE_FLOOR
    }
    if not weak:
        return _passed(rule, "Every declaration was read clearly.")
    worst = min(weak, key=lambda k: weak[k])
    return _review(
        rule,
        f"{len(weak)} declaration(s) were read with low confidence, the weakest being "
        f"{_label(worst)} at {weak[worst]:.0%}. Check contrast and whether anything obscures them.",
        detail={"low_confidence_fields": weak},
    )


@check("declaration_grouping")
def check_declaration_grouping(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    """Rule 6(2) wants the mandatory declarations given as one group, not scattered."""
    boxes = [
        (k, v.bbox, v.image_id)
        for k, v in ctx.fields.items()
        if v.present and v.bbox and len(v.bbox) == 4
    ]
    if len(boxes) < 3:
        return _review(rule, "Too few declarations were located to judge how they are grouped.")

    per_image = Counter(img for _, _, img in boxes)
    if len(per_image) > 2:
        return _failed(
            rule,
            f"{rule.message_fail} They are spread across {len(per_image)} panels.",
            detail={"panels": len(per_image)},
        )

    # Judge grouping on the panel carrying most of the declarations.
    main_image, _ = per_image.most_common(1)[0]
    on_main = [bbox for _, bbox, img in boxes if img == main_image]

    xs = [b[0] for b in on_main] + [b[0] + b[2] for b in on_main]
    ys = [b[1] for b in on_main] + [b[1] + b[3] for b in on_main]
    hull = (max(xs) - min(xs)) * (max(ys) - min(ys))
    ink = sum(b[2] * b[3] for b in on_main)
    density = ink / hull if hull else 0.0
    detail = {"density": round(density, 3), "panels": len(per_image)}

    if density < 0.08:
        return _review(
            rule,
            f"The declarations occupy only {density:.0%} of the area they span, which may mean "
            "they are scattered rather than grouped. Confirm visually.",
            detail=detail,
        )
    return _passed(rule, "The mandatory declarations are grouped together.", detail=detail)


# --------------------------------------------------------------------------- geometry


def _geometry_basis(ctx: ScanContext) -> str:
    net = ctx.get("net_quantity")
    basis = units.basis_of(net.attribute("unit")) if net else None
    return str(basis) if basis else "WEIGHT"


def _no_scale(rule: Rule, ctx: ScanContext) -> FindingResult | None:
    """Geometry is unjudgeable without a millimetre scale. Say so plainly."""
    if ctx.mm_per_px is None:
        return _review(
            rule,
            "Character height cannot be measured because the photograph has no scale "
            "reference. Re-photograph with the scale card in frame, or measure the pack "
            "directly.",
            detail={"reason": "no_scale"},
        )
    # Falsy rather than None: an area of zero picks the smallest, most lenient height
    # band, so a collapsed detection would quietly clear undersized print.
    if not ctx.pdp_area_cm2:
        return _review(
            rule,
            "The required height depends on the area of the principal display panel, which "
            "was not determined for this scan.",
            detail={"reason": "no_pdp_area"},
        )
    return None


@check("glyph_height")
def check_glyph_height(rule: Rule, ctx: ScanContext, rs: RuleSet) -> FindingResult:
    value = ctx.get(rule.field_key or "")
    if value is None:
        return _not_applicable(rule, "The declaration this rule measures was not found.")
    if (blocked := _no_scale(rule, ctx)) is not None:
        return blocked
    if value.glyph_height_mm is None:
        return _review(rule, "Character height could not be measured for this declaration.")

    table = rs.table_for_basis(_geometry_basis(ctx))
    required, band = table.required_mm(ctx.pdp_area_cm2 or 0.0, raised=ctx.is_raised)
    measured = value.glyph_height_mm
    detail = {
        "measured_mm": round(measured, 2),
        "required_mm": required,
        "pdp_area_cm2": round(ctx.pdp_area_cm2 or 0.0, 1),
        "table": table.citation,
        "band": band,
        "raised": ctx.is_raised,
        "tolerance": GEOMETRY_TOLERANCE,
    }

    if measured >= required:
        return _passed(
            rule,
            f"Measured {measured:.1f} mm against the {required:.1f} mm required for a "
            f"principal display panel of {ctx.pdp_area_cm2:.0f} cm².",
            detail=detail,
            evidence=value,
        )
    if measured >= required * (1 - GEOMETRY_TOLERANCE):
        return _review(
            rule,
            f"Measured {measured:.1f} mm against {required:.1f} mm required — short, but "
            f"inside the {GEOMETRY_TOLERANCE:.0%} measurement tolerance. "
            "Measure the pack directly.",
            detail=detail,
            evidence=value,
        )
    return _failed(
        rule,
        f"Net quantity numerals measure {measured:.1f} mm. {table.citation} requires "
        f"{required:.1f} mm for a principal display panel of {ctx.pdp_area_cm2:.0f} cm².",
        detail=detail,
        evidence=value,
    )


@check("glyph_height_minimum")
def check_glyph_height_minimum(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    if (blocked := _no_scale(rule, ctx)) is not None:
        return blocked
    required = (rule.min_mm_raised if ctx.is_raised else rule.min_mm) or 1.0
    measured = {
        k: ctx.fields[k].glyph_height_mm
        for k in rule.field_keys
        if ctx.get(k) and ctx.fields[k].glyph_height_mm is not None
    }
    if not measured:
        return _review(rule, "No declaration could be measured for minimum height.")

    worst_key = min(measured, key=lambda k: measured[k])
    worst = measured[worst_key]
    detail = {
        "measured_mm": round(worst, 2),
        "required_mm": required,
        "field": worst_key,
        "all_measured": {k: round(v, 2) for k, v in measured.items()},
        "tolerance": GEOMETRY_TOLERANCE,
    }

    if worst >= required:
        return _passed(
            rule,
            f"The shortest declaration measured is {_label(worst_key)} at {worst:.1f} mm, "
            f"above the {required:.1f} mm minimum.",
            detail=detail,
            evidence=ctx.get(worst_key),
        )
    if worst >= required * (1 - GEOMETRY_TOLERANCE):
        return _review(
            rule,
            f"{_label(worst_key).capitalize()} measures {worst:.1f} mm against a {required:.1f} mm "
            "minimum, inside measurement tolerance. Measure the pack directly.",
            detail=detail,
            evidence=ctx.get(worst_key),
        )
    return _failed(
        rule,
        f"{_label(worst_key).capitalize()} measures {worst:.1f} mm, below the {required:.1f} mm "
        "minimum height for declaration lettering.",
        detail=detail,
        evidence=ctx.get(worst_key),
    )


@check("glyph_width_ratio")
def check_glyph_width_ratio(rule: Rule, ctx: ScanContext, _rs: RuleSet) -> FindingResult:
    if (blocked := _no_scale(rule, ctx)) is not None:
        return blocked
    min_ratio = rule.min_ratio or (1 / 3)
    ratios: dict[str, float] = {}
    for key in rule.field_keys:
        v = ctx.get(key)
        if v and v.glyph_height_mm and v.glyph_width_mm:
            ratios[key] = v.glyph_width_mm / v.glyph_height_mm
    if not ratios:
        return _review(rule, "Character width could not be measured for any declaration.")

    worst_key = min(ratios, key=lambda k: ratios[k])
    worst = ratios[worst_key]
    detail = {
        "measured_ratio": round(worst, 3),
        "required_ratio": round(min_ratio, 3),
        "field": worst_key,
    }
    if worst >= min_ratio:
        return _passed(
            rule,
            f"Narrowest lettering is {worst:.2f} of its height, above the "
            f"{min_ratio:.2f} minimum.",
            detail=detail,
            evidence=ctx.get(worst_key),
        )
    return _failed(
        rule,
        f"{_label(worst_key).capitalize()} lettering is {worst:.2f} of its height, below the "
        f"one-third minimum.",
        detail=detail,
        evidence=ctx.get(worst_key),
    )


# --------------------------------------------------------------------------- exemptions


def match_exemption(ctx: ScanContext, rs: RuleSet) -> Exemption | None:
    """Rule 26. Returns the first exemption that covers this package, if any."""
    net = ctx.get("net_quantity")
    qty = _num(net.attribute("value")) if net else None
    unit = units.canonical(net.attribute("unit")) if net else None
    category = (ctx.category or "").upper()
    base = units.to_base(qty, unit) if qty is not None and unit else None

    def _limit(limits: dict[str, Any]) -> float | None:
        """The limit expressed in the same basis as the declared quantity."""
        for u, v in limits.items():
            amount = _num(v)
            if amount is not None and units.basis_of(u) == units.basis_of(unit):
                return units.to_base(amount, u)
        return None

    for ex in rs.exemptions:
        when = ex.when
        if (allowed := when.get("category_in")) and category not in {c.upper() for c in allowed}:
            continue
        if (blocked := when.get("category_not_in")) and category in {c.upper() for c in blocked}:
            continue
        if limits := when.get("net_quantity_max"):
            ceiling = _limit(limits)
            if base is None or ceiling is None or base > ceiling:
                continue
        if limits := when.get("net_quantity_min"):
            floor = _limit(limits)
            if base is None or floor is None or base < floor:
                continue
        return ex
    return None


# --------------------------------------------------------------------------- evaluate


def _applies(rule: Rule, ctx: ScanContext) -> bool:
    if ctx.channel not in rule.applies_to:
        return False
    return all(getattr(ctx, key, None) == expected for key, expected in rule.only_when.items())


def evaluate(ctx: ScanContext, rs: RuleSet) -> tuple[list[FindingResult], Exemption | None]:
    """Judge one scan. Returns the findings and the exemption applied, if any."""
    try:
        exemption = match_exemption(ctx, rs)
    except Exception:  # an unjudgeable exemption must not stop the scan being judged
        exemption = None
    findings: list[FindingResult] = []

    for rule in rs.rules:
        if not _applies(rule, ctx):
            reason = (
                f"Not required on an {ctx.channel.value.lower()} listing."
                if ctx.channel not in rule.applies_to
                else "This rule does not apply to this package."
            )
            findings.append(_not_applicable(rule, reason))
            continue

        if exemption and rule.skip_when_exempt:
            findings.append(
                _not_applicable(
                    rule,
                    f"Exempt under {exemption.citation} — {exemption.description}",
                )
            )
            continue

        fn = CHECKS.get(rule.check)
        if fn is None:
            findings.append(_review(rule, f"No implementation for check kind “{rule.check}”."))
            continue
        try:
            findings.append(fn(rule, ctx, rs))
        except Exception as exc:  # a broken rule must not sink the whole scan
            findings.append(_review(rule, f"This rule could not be evaluated: {exc}"))

    return findings, exemption


def coverage(findings: list[FindingResult]) -> tuple[int, int]:
    """How many of the applicable rules were actually decided, and how many applied.

    A score means nothing without this. A pack whose scan read a single line can be
    "100%" on the two rules it managed to decide, which reads as a clean bill of
    health for a product nobody assessed. Anything that displays a score must show
    the coverage beside it.
    """
    applicable = [f for f in findings if f.status is not FindingStatus.NA]
    decided = [f for f in applicable if f.status in (FindingStatus.PASS, FindingStatus.FAIL)]
    return len(decided), len(applicable)


def score(findings: list[FindingResult]) -> float | None:
    """0–100 over the rules that were actually decided, weighted by severity.

    None when nothing could be decided. A scan that read nothing must not report
    0/100: a zero is a judgement about the product, and "we could not assess this"
    is not a judgement about the product at all.
    """
    graded = [f for f in findings if f.status in (FindingStatus.PASS, FindingStatus.FAIL)]
    if not graded:
        return None
    total = sum(SEVERITY_WEIGHT[Severity(f.severity)] for f in graded)
    lost = sum(
        SEVERITY_WEIGHT[Severity(f.severity)] for f in graded if f.status is FindingStatus.FAIL
    )
    return round(100.0 * (total - lost) / total, 1)


def verdict(findings: list[FindingResult], value: float | None) -> Verdict:
    # Any failure at all makes the package non-compliant; severity governs how far the
    # score falls and how the finding is ranked, not whether it counts as a violation.
    if any(f.status is FindingStatus.FAIL for f in findings):
        return Verdict.NON_COMPLIANT
    if value is None or any(f.status is FindingStatus.NEEDS_REVIEW for f in findings):
        return Verdict.INCONCLUSIVE
    return Verdict.COMPLIANT if value >= PASS_THRESHOLD else Verdict.INCONCLUSIVE
