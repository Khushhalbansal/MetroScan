"""The Measure: a Rule 8 finding expressed as a millimetre scale.

This is the signature element of the product, and the reason it exists is substantive
rather than decorative. Rule 8 does not ask whether a label looks right; it asks whether
a letter is at least N millimetres tall. A badge reading "font too small" throws away
the only thing the finding actually contains — how short, against what limit, on a panel
of what area. A graduated scale with a limit line keeps all of it, and an officer can
check the claim by holding a rule against the pack.

The geometry is computed here, as plain data, so the same numbers drive the PDF and the
web view and the two cannot drift. Nothing in this module draws anything.
"""

from __future__ import annotations

from dataclasses import dataclass

# Never draw a scale shorter than this: a 0.4 mm measurement against a 1 mm limit on a
# scale that stopped at 1 mm would read as a near miss rather than a gross shortfall.
MIN_SCALE_MM = 6.0

# Headroom above the larger of measured/required, so the limit line is never flush
# against the end of the rule.
HEADROOM = 1.35


@dataclass(frozen=True)
class Tick:
    mm: float
    position: float  # 0-100, percentage along the scale
    major: bool
    label: str | None


@dataclass(frozen=True)
class Measure:
    """One Rule 8 finding as a scale reading."""

    measured_mm: float | None
    required_mm: float
    scale_max_mm: float
    ticks: tuple[Tick, ...]
    # Percentages along the scale, for whatever draws it.
    measured_position: float | None
    required_position: float
    compliant: bool
    citation: str | None = None
    band: str | None = None
    pdp_area_cm2: float | None = None

    @property
    def shortfall_mm(self) -> float | None:
        """How far below the limit, or None when it meets it (or was not measured)."""
        if self.measured_mm is None or self.measured_mm >= self.required_mm:
            return None
        return round(self.required_mm - self.measured_mm, 2)


def _scale_max(measured: float | None, required: float) -> float:
    largest = max(required, measured or 0.0)
    return max(MIN_SCALE_MM, float(int(largest * HEADROOM) + 1))


def build(
    *,
    measured_mm: float | None,
    required_mm: float,
    citation: str | None = None,
    band: str | None = None,
    pdp_area_cm2: float | None = None,
) -> Measure:
    """Lay out a scale for one measurement against one limit.

    `measured_mm` may be None — the scan could not measure this declaration, either
    because there was no scale reference in frame or because the text was not found.
    The scale is still drawn, showing the requirement, with no index on it. That is
    honest: it shows what the rule demands while making plain that nothing was measured.
    """
    scale_max = _scale_max(measured_mm, required_mm)

    ticks: list[Tick] = []
    # A tick every half millimetre, tall on the whole numbers. Uneven graduation is
    # what makes a rule readable at a glance rather than a row of identical lines.
    steps = int(scale_max * 2)
    for step in range(steps + 1):
        mm = step / 2
        major = step % 2 == 0
        ticks.append(
            Tick(
                mm=mm,
                position=round(100.0 * mm / scale_max, 4),
                major=major,
                label=f"{mm:g}" if major else None,
            )
        )

    return Measure(
        measured_mm=measured_mm,
        required_mm=required_mm,
        scale_max_mm=scale_max,
        ticks=tuple(ticks),
        measured_position=(
            round(100.0 * min(measured_mm, scale_max) / scale_max, 4)
            if measured_mm is not None
            else None
        ),
        required_position=round(100.0 * min(required_mm, scale_max) / scale_max, 4),
        compliant=measured_mm is not None and measured_mm >= required_mm,
        citation=citation,
        band=band,
        pdp_area_cm2=pdp_area_cm2,
    )


def from_finding(detail: dict, citation: str | None = None) -> Measure | None:
    """Build a Measure from a geometry finding's detail, or None if it is not one.

    The engine puts `measured_mm` and `required_mm` in the detail of every Rule 8
    check. A finding without `required_mm` is not a measurement and gets no ruler —
    drawing one for a presence check would be inventing a reading.
    """
    required = detail.get("required_mm")
    if required is None:
        return None
    try:
        required_mm = float(required)
    except (TypeError, ValueError):
        return None

    measured = detail.get("measured_mm")
    try:
        measured_mm = float(measured) if measured is not None else None
    except (TypeError, ValueError):
        measured_mm = None

    area = detail.get("pdp_area_cm2")
    return build(
        measured_mm=measured_mm,
        required_mm=required_mm,
        citation=citation or detail.get("table"),
        band=detail.get("band"),
        pdp_area_cm2=float(area) if isinstance(area, int | float) else None,
    )
