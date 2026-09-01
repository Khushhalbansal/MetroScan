"""Structured declarations — what the extractor understood, as typed values.

The boundary this module draws is the important one:

    raw_text  is EVIDENCE. It is shown to the officer, quoted in reports, and
              highlighted on the image. No rule may judge it.
    parsed    is FACT. It is what the extractor understood, and it is the only
              thing a rule is allowed to reason about.

Every recurring bug in this pipeline came from crossing that line — a rule
re-matching text the extractor had already parsed, with boundary assumptions real
OCR output violates. `\\b\\d{6}\\b` does not find the PIN in "Maharashtra422010";
`\\bRs\\.?\\b` does not find the marking in "MRPRs.45.00". Both were correct in the
extractor and wrong in the rule, because the parsing was written twice.

So parsing happens once, here, and the result is a typed object. A rule names an
attribute of that object; the ruleset loader checks the attribute exists when the
file loads, so a mistyped name is a startup error rather than a silent None that
reads as a missing declaration.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from app.models.enums import FieldKey
from app.rules.units import Basis


@dataclass(frozen=True)
class Declaration:
    """Base for every parsed declaration."""

    @classmethod
    def attributes(cls) -> frozenset[str]:
        return frozenset(f.name for f in dataclasses.fields(cls))

    def attribute(self, name: str) -> Any:
        """Read one attribute. Unknown names raise rather than returning None.

        A silent None here would be indistinguishable from a genuinely absent
        declaration, which is the difference between "we did not parse this" and
        "the package does not carry this" — the one distinction the whole system
        turns on.
        """
        if name not in self.attributes():
            raise AttributeError(
                f"{type(self).__name__} has no attribute {name!r}; "
                f"known attributes are {sorted(self.attributes())}"
            )
        return getattr(self, name)

    def as_dict(self) -> dict[str, Any]:
        """For persistence and for the API. Not for judgement."""
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class PriceDeclaration(Declaration):
    """A retail sale price, Rule 6(1)(e)."""

    amount: float | None = None
    # The marking as printed ("Rs.", "₹", "INR"), or None if the pack carried none.
    currency_mark: str | None = None
    # Every price found on the pack, so a dual declaration is visible to the rules.
    all_amounts: tuple[float, ...] = ()
    inclusive_of_taxes: bool = False


@dataclass(frozen=True)
class QuantityDeclaration(Declaration):
    """A net quantity, Rule 6(1)(c)."""

    value: float | None = None
    unit: str | None = None  # canonical, per app.rules.units
    basis: Basis | None = None
    # True when the quantity carried no "Net Qty" style label and was inferred.
    unlabelled: bool = False


@dataclass(frozen=True)
class DateDeclaration(Declaration):
    """A month and year of manufacture, packing or import, Rule 6(1)(d)."""

    month: int | None = None
    year: int | None = None


@dataclass(frozen=True)
class AddressDeclaration(Declaration):
    """A postal address. `pin` is the parsed 6-digit code, however it was printed."""

    pin: str | None = None


@dataclass(frozen=True)
class UnitPriceDeclaration(Declaration):
    """A unit sale price, Rule 6(11)."""

    amount: float | None = None
    per_unit: str | None = None  # canonical


@dataclass(frozen=True)
class OriginDeclaration(Declaration):
    """A country of origin, for imported packages."""

    country: str | None = None


@dataclass(frozen=True)
class EmailDeclaration(Declaration):
    address: str | None = None


@dataclass(frozen=True)
class PhoneDeclaration(Declaration):
    digits: str | None = None


@dataclass(frozen=True)
class NameDeclaration(Declaration):
    """A declaration whose whole content is its text — a name, a batch code."""

    text: str | None = None


# Which parsed type each declaration carries. The ruleset loader validates every
# rule against this, so a rule can only name a field/attribute pair that exists.
DECLARATION_TYPES: dict[str, type[Declaration]] = {
    FieldKey.MRP: PriceDeclaration,
    FieldKey.NET_QUANTITY: QuantityDeclaration,
    FieldKey.MFG_DATE: DateDeclaration,
    FieldKey.MANUFACTURER_ADDRESS: AddressDeclaration,
    FieldKey.CONSUMER_CARE_ADDRESS: AddressDeclaration,
    FieldKey.UNIT_SALE_PRICE: UnitPriceDeclaration,
    FieldKey.COUNTRY_OF_ORIGIN: OriginDeclaration,
    FieldKey.CONSUMER_CARE_EMAIL: EmailDeclaration,
    FieldKey.CONSUMER_CARE_PHONE: PhoneDeclaration,
    FieldKey.MANUFACTURER_NAME: NameDeclaration,
    FieldKey.CONSUMER_CARE_NAME: NameDeclaration,
    FieldKey.COMMON_NAME: NameDeclaration,
    FieldKey.BATCH_NUMBER: NameDeclaration,
    FieldKey.FSSAI_NUMBER: NameDeclaration,
    FieldKey.IMPORTER_NAME: NameDeclaration,
}


def declaration_type(field_key: str) -> type[Declaration] | None:
    return DECLARATION_TYPES.get(field_key)


def attributes_of(field_key: str) -> frozenset[str]:
    """Attribute names a rule may name for this declaration."""
    kind = DECLARATION_TYPES.get(field_key)
    return kind.attributes() if kind is not None else frozenset()
