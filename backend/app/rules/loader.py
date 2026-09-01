"""Load dated rulesets from /rules and pick the one in force on a given date."""

from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import settings
from app.models.enums import Channel, Severity
from app.rules.schema import Exemption, GeometryBand, GeometryTable, Rule, RuleSet

log = logging.getLogger(__name__)


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_ruleset(raw: dict) -> RuleSet:
    meta = raw.get("meta", {})

    tables: dict[str, GeometryTable] = {}
    for name, spec in (raw.get("geometry_tables") or {}).items():
        tables[name] = GeometryTable(
            name=name,
            citation=spec.get("citation", "Rule 8"),
            basis=tuple(str(b).upper() for b in spec.get("basis", [])),
            bands=tuple(
                GeometryBand(
                    max_cm2=band.get("max_cm2"),
                    normal_mm=float(band["normal_mm"]),
                    raised_mm=float(band["raised_mm"]),
                )
                for band in spec.get("bands", [])
            ),
        )

    exemptions = tuple(
        Exemption(
            id=e["id"],
            citation=e.get("citation", ""),
            description=e.get("description", ""),
            when=e.get("when", {}),
        )
        for e in (raw.get("exemptions") or [])
    )

    rules: list[Rule] = []
    for r in raw.get("rules", []):
        rules.append(
            Rule(
                id=r["id"],
                title=r["title"],
                citation=r["citation"],
                check=r["check"],
                severity=Severity(r.get("severity", "MAJOR")),
                applies_to=tuple(Channel(c) for c in r.get("applies_to", ["PHYSICAL"])),
                message_fail=r["message_fail"],
                remediation=r.get("remediation"),
                note=r.get("note"),
                skip_when_exempt=bool(r.get("skip_when_exempt", True)),
                only_when=r.get("only_when") or {},
                field_key=r.get("field"),
                field_keys=tuple(r.get("fields", ())),
                attributes=tuple(r.get("attributes", ())),
                flag=r.get("flag"),
                min_mm=r.get("min_mm"),
                min_mm_raised=r.get("min_mm_raised"),
                min_ratio=r.get("min_ratio"),
            )
        )

    return RuleSet(
        version=str(meta.get("version", "unversioned")),
        effective_date=_as_date(meta.get("effective_date", "2011-04-01")),
        description=str(meta.get("description", "")).strip(),
        source=str(meta.get("source", "")),
        tables=tables,
        exemptions=exemptions,
        rules=tuple(rules),
    )


class RulesetContractError(ValueError):
    """A rule names a field or attribute that does not exist."""


def validate_contract(ruleset: RuleSet) -> None:
    """Check every rule against the declaration types it reasons about.

    A rule naming an attribute the declaration does not have used to read back as
    None, which is indistinguishable from "the package does not carry this" — so a
    typo in the YAML became a fabricated violation on every scan. Raising here turns
    that from a silent, product-condemning bug into a startup failure.

    Imported inside the function: declarations imports FieldKey and units, and the
    rules package is imported by the pipeline, so a module-level import would close
    a cycle.
    """
    from app.pipeline.declarations import DECLARATION_TYPES, attributes_of

    problems: list[str] = []
    for rule in ruleset.rules:
        named = [k for k in (rule.field_key, *rule.field_keys) if k]
        for key in named:
            if key not in DECLARATION_TYPES:
                problems.append(
                    f"{rule.id}: names field {key!r}, which has no declaration type"
                )
        if rule.check == "attribute":
            if not rule.field_key:
                problems.append(f"{rule.id}: check 'attribute' needs a field")
                continue
            if not rule.attributes:
                problems.append(f"{rule.id}: check 'attribute' needs at least one attribute")
            known = attributes_of(rule.field_key)
            for name in rule.attributes:
                if name not in known:
                    problems.append(
                        f"{rule.id}: {rule.field_key!r} has no attribute {name!r} "
                        f"(known: {sorted(known)})"
                    )
        elif rule.attributes:
            problems.append(
                f"{rule.id}: check {rule.check!r} does not use attributes, "
                f"but {list(rule.attributes)} were given"
            )

    if problems:
        raise RulesetContractError(
            f"ruleset {ruleset.version} does not match the declarations it judges:\n  "
            + "\n  ".join(problems)
        )


def load_ruleset_file(path: Path) -> RuleSet:
    ruleset = parse_ruleset(yaml.safe_load(path.read_text(encoding="utf-8")))
    validate_contract(ruleset)
    return ruleset


@lru_cache(maxsize=1)
def _all_rulesets() -> tuple[RuleSet, ...]:
    files = sorted(Path(settings.rules_dir).glob("*.yaml"))
    if not files:
        raise FileNotFoundError(f"No rulesets found in {settings.rules_dir}")
    return tuple(sorted((load_ruleset_file(f) for f in files), key=lambda rs: rs.effective_date))


def available_versions() -> list[str]:
    return [rs.version for rs in _all_rulesets()]


def ruleset_for_date(on: date | None = None) -> RuleSet:
    """The latest ruleset already in force on `on` (defaults to today)."""
    on = on or date.today()
    in_force = [rs for rs in _all_rulesets() if rs.effective_date <= on]
    if in_force:
        return in_force[-1]

    # No ruleset had taken effect by this date. Judging the scan anyway applies rules
    # that did not yet exist — a pack from 2015 would be marked non-compliant for
    # lacking the Unit Sale Price required from 2022. The earliest available set is
    # still returned so nothing breaks, but this must never pass unremarked.
    earliest = _all_rulesets()[0]
    log.warning(
        "No ruleset was in force on %s; judging with %s (effective %s). Findings may "
        "cite rules that post-date the scan.",
        on, earliest.version, earliest.effective_date,
    )
    return earliest


def ruleset_by_version(version: str) -> RuleSet:
    for rs in _all_rulesets():
        if rs.version == version:
            return rs
    raise KeyError(f"Unknown ruleset version: {version}")


def reload_rulesets() -> None:
    """Drop the cache after an admin publishes an edited ruleset."""
    _all_rulesets.cache_clear()
