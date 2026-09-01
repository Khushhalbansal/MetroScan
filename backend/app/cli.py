"""Operator commands.

    python -m app.cli create-admin --email you@example.gov.in --name "A Name"
    python -m app.cli prune-scans          # run the retention auto-deletion job

`create-admin`: the first administrator has to come from somewhere, and the two usual
answers are both wrong: seeding a fixed account with a known password ships a backdoor,
and letting the first anonymous caller claim the role turns a public server into a
race. So it is done here, by whoever has shell access to the machine, once. The
password is read from the environment or generated and printed. It is never a default
and never stored anywhere but the argon2 hash.

`prune-scans`: the cron entry point for Feature 6. Put it in the system crontab; it
soft-deletes scans an officer marked `case_open = False` whose retention window has
elapsed, logs each to the audit trail, and touches nothing else.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.schema_state import inspect_schema
from app.core.security import WeakPassword, hash_password
from app.models.enums import Role
from app.models.tables import User
from app.services import audit

# Four words from a wide list is comfortably stronger than the twelve-character floor
# and can be typed on a phone. Generated with secrets, not random.
WORDS = (
    "beam", "brass", "caliper", "cistern", "damper", "ferrule", "gasket", "gauge",
    "gnomon", "hasp", "ingot", "jigger", "kelvin", "lattice", "mandrel", "notch",
    "ohm", "plumb", "quill", "ratchet", "sextant", "tare", "vernier", "weight",
)


def _generate_password() -> str:
    return "-".join(secrets.choice(WORDS) for _ in range(4)) + "-" + secrets.token_hex(2)


def create_admin(email: str, full_name: str, jurisdiction: str | None) -> int:
    db = SessionLocal()
    try:
        report = inspect_schema(db.get_bind())
        if not report.writable:
            print(f"error: {report.message}", file=sys.stderr)
            return 2

        if db.execute(select(User).where(User.email == email)).scalars().first():
            print(f"error: an account already exists for {email}.", file=sys.stderr)
            return 1

        password = os.environ.get("ADMIN_PASSWORD") or _generate_password()
        try:
            password_hash = hash_password(password)
        except WeakPassword as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        user = User(
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            role=Role.ADMIN,
            jurisdiction=jurisdiction,
            is_active=True,
        )
        db.add(user)
        db.flush()
        audit.record(
            db,
            action=audit.Action.USER_CREATED,
            entity_type="user",
            entity_id=user.id,
            actor=user,  # self-created: the bootstrap is attributable to the account itself
            after={"email": email, "role": Role.ADMIN.value, "via": "cli"},
        )
        db.commit()

        print(f"Created administrator {email}")
        if "ADMIN_PASSWORD" not in os.environ:
            print(f"Password: {password}")
            print("Shown once. Store it in a password manager now.")
        return 0
    finally:
        db.close()


def prune_scans() -> int:
    """Run the retention auto-deletion job once."""
    from app.services import retention

    db = SessionLocal()
    try:
        report = inspect_schema(db.get_bind())
        if not report.writable:
            print(f"error: {report.message}", file=sys.stderr)
            return 2
        deleted = retention.run_auto_deletion(db)
        if deleted:
            print(f"Soft-deleted {len(deleted)} scan(s): {', '.join(deleted)}")
        else:
            print("No scans are past the retention window.")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Create the first administrator account.")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True, dest="full_name")
    admin.add_argument("--jurisdiction", default=None)

    sub.add_parser("prune-scans", help="Run the retention auto-deletion job.")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.full_name, args.jurisdiction)
    if args.command == "prune-scans":
        return prune_scans()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
