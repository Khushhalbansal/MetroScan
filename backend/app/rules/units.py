"""Standard units recognised for net quantity declarations, and their measurement basis."""

from __future__ import annotations

from enum import StrEnum


class Basis(StrEnum):
    WEIGHT = "WEIGHT"
    VOLUME = "VOLUME"
    LENGTH = "LENGTH"
    AREA = "AREA"
    NUMBER = "NUMBER"


# canonical unit -> (basis, factor to the base unit of that basis)
UNITS: dict[str, tuple[Basis, float]] = {
    # weight, base gram
    "mg": (Basis.WEIGHT, 0.001),
    "g": (Basis.WEIGHT, 1.0),
    "kg": (Basis.WEIGHT, 1000.0),
    # volume, base millilitre
    "ml": (Basis.VOLUME, 1.0),
    "cl": (Basis.VOLUME, 10.0),
    "l": (Basis.VOLUME, 1000.0),
    # length, base centimetre
    "mm": (Basis.LENGTH, 0.1),
    "cm": (Basis.LENGTH, 1.0),
    "m": (Basis.LENGTH, 100.0),
    # area, base square centimetre
    "cm2": (Basis.AREA, 1.0),
    "m2": (Basis.AREA, 10000.0),
    # number
    "n": (Basis.NUMBER, 1.0),
    "u": (Basis.NUMBER, 1.0),
    "pc": (Basis.NUMBER, 1.0),
    "pcs": (Basis.NUMBER, 1.0),
}

# how a unit may be written on a pack -> canonical key
ALIASES: dict[str, str] = {
    "gm": "g",
    "gms": "g",
    "ltr": "l",
    "ltrs": "l",
    "gram": "g",
    "grams": "g",
    "gramme": "g",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "milligram": "mg",
    "millilitre": "ml",
    "milliliter": "ml",
    "mls": "ml",
    "litre": "l",
    "liter": "l",
    "litres": "l",
    "liters": "l",
    "lit": "l",
    "metre": "m",
    "meter": "m",
    "metres": "m",
    "meters": "m",
    "sqcm": "cm2",
    "sqm": "m2",
    "piece": "pc",
    "pieces": "pcs",
    "nos": "n",
    "no": "n",
    "units": "u",
    "unit": "u",
}


def canonical(unit: str | None) -> str | None:
    """Normalise a unit as written on a pack to a canonical key, or None if unrecognised."""
    if not unit:
        return None
    key = unit.strip().lower().replace(".", "").replace("²", "2").replace(" ", "")
    key = ALIASES.get(key, key)
    return key if key in UNITS else None


def basis_of(unit: str | None) -> Basis | None:
    key = canonical(unit)
    return UNITS[key][0] if key else None


def to_base(value: float, unit: str) -> float | None:
    """Convert to the base unit of its basis (g, ml, cm, cm², count)."""
    key = canonical(unit)
    if not key:
        return None
    return value * UNITS[key][1]
