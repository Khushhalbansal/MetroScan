"""Authentication, roles, the audit trail, and officer overrides.

The invariant that carries the most weight here is the last one: an officer may
overrule the machine, and doing so must never erase what the machine decided. A system
where the automated verdict disappears the moment a human disagrees with it cannot be
audited, and its reports cannot be defended — the one thing a manufacturer's counsel
will ask is what the software originally found.
"""

from __future__ import annotations

import time

import pytest

from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models.enums import FindingStatus, Role
from app.pipeline import engine_ocr
from tests.authfixtures import (
    ADMIN_PASSWORD,
    API,
    OFFICER_PASSWORD,
    auth,
    build_app,
    seed_user,
    token_for,
)
from tests.test_api_scan import COMPLIANT_LINES, ScriptedEngine, png

ADMIN_EMAIL = "controller@metrology.gov.in"
OFFICER_EMAIL = "officer@metrology.gov.in"


@pytest.fixture
def app_with_users(tmp_path, monkeypatch):
    client, Session = build_app(tmp_path, monkeypatch)
    seed_user(Session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, role=Role.ADMIN)
    seed_user(Session, email=OFFICER_EMAIL, password=OFFICER_PASSWORD, role=Role.SENIOR_OFFICER)
    with client:
        yield client, Session


@pytest.fixture
def scripted(request):
    lines = getattr(request, "param", COMPLIANT_LINES)
    previous = engine_ocr._engine
    engine_ocr.set_engine(ScriptedEngine(lines))
    yield
    engine_ocr._engine = previous


# ----------------------------------------------------------------- hashing & tokens


def test_a_password_is_never_stored_in_the_clear():
    stored = hash_password("vernier-caliper-brass-0001")
    assert "vernier" not in stored
    assert stored.startswith("$argon2")
    assert verify_password("vernier-caliper-brass-0001", stored)
    assert not verify_password("vernier-caliper-brass-0002", stored)


def test_two_identical_passwords_hash_differently():
    """Unsalted hashes let one leak reveal every officer who reused a password."""
    assert hash_password("a-long-enough-passphrase") != hash_password("a-long-enough-passphrase")


def test_a_short_password_is_refused():
    from app.core.security import WeakPassword

    with pytest.raises(WeakPassword, match="at least 12"):
        hash_password("short")


def test_verifying_against_no_stored_hash_is_false_not_an_error():
    """The unknown-account path. It must cost the same as a wrong password."""
    assert verify_password("anything at all", None) is False


def test_a_refresh_token_is_not_accepted_as_an_access_token():
    """Otherwise a stolen refresh token is a fortnight of API access."""
    refresh = create_token("user-1", "refresh")
    assert decode_token(refresh, expect="refresh") is not None
    assert decode_token(refresh, expect="access") is None


def test_a_tampered_token_is_rejected():
    token = create_token("user-1", "access", role="ADMIN")
    head, payload, signature = token.split(".")
    forged = f"{head}.{payload}.{'a' * len(signature)}"
    assert decode_token(forged, expect="access") is None


def test_an_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.access_token_ttl_minutes", -1)
    assert decode_token(create_token("user-1", "access"), expect="access") is None


# ------------------------------------------------------------------------- sign-in


def test_an_officer_can_sign_in(app_with_users):
    client, _ = app_with_users
    response = client.post(
        f"{API}/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_a_wrong_password_and_an_unknown_email_are_indistinguishable(app_with_users):
    """Different messages would let anyone enumerate which officers have accounts."""
    client, _ = app_with_users
    wrong = client.post(
        f"{API}/auth/login", json={"email": OFFICER_EMAIL, "password": "not-the-password"}
    )
    unknown = client.post(
        f"{API}/auth/login", json={"email": "nobody@metrology.gov.in", "password": "whatever12345"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_a_deactivated_account_cannot_sign_in(app_with_users):
    client, Session = app_with_users
    seed_user(
        Session,
        email="retired@metrology.gov.in",
        password=OFFICER_PASSWORD,
        role=Role.SENIOR_OFFICER,
        is_active=False,
    )
    response = client.post(
        f"{API}/auth/login",
        json={"email": "retired@metrology.gov.in", "password": OFFICER_PASSWORD},
    )
    assert response.status_code == 401


def test_deactivation_takes_effect_on_the_next_request_not_the_next_login(app_with_users):
    """The reason the user is loaded per request rather than trusted from the token.

    An officer whose access is withdrawn keeps a valid signed token for hours. If the
    token's claims were believed, so would their access be.
    """
    client, Session = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    officer_token = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))

    assert client.get(f"{API}/auth/me", headers=officer_token).status_code == 200

    users = client.get(f"{API}/auth/users", headers=admin).json()
    officer_id = next(u["id"] for u in users if u["email"] == OFFICER_EMAIL)
    disabled = client.post(f"{API}/auth/users/{officer_id}:deactivate", headers=admin)
    assert disabled.status_code == 200

    assert client.get(f"{API}/auth/me", headers=officer_token).status_code == 403


def test_a_refresh_token_renews_a_session(app_with_users):
    client, _ = app_with_users
    tokens = client.post(
        f"{API}/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASSWORD}
    ).json()
    time.sleep(1)  # iat has one-second resolution; without this the tokens are identical
    renewed = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert renewed.status_code == 200
    assert renewed.json()["access_token"] != tokens["access_token"]


def test_an_access_token_cannot_be_used_to_refresh(app_with_users):
    client, _ = app_with_users
    tokens = client.post(
        f"{API}/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASSWORD}
    ).json()
    response = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401


# ------------------------------------------------------------------- authorisation


def test_every_scan_endpoint_refuses_an_anonymous_caller(app_with_users):
    client, _ = app_with_users
    assert client.get(f"{API}/scans").status_code == 401
    assert client.get(f"{API}/scans/{'0' * 32}").status_code == 401
    assert client.post(
        f"{API}/scans",
        files=[("images", ("f.png", png(), "image/png"))],
        data={"product_name": "X"},
    ).status_code == 401


def test_a_missing_and_a_malformed_token_look_the_same(app_with_users):
    """Both are 401. A 403 for one of them tells a caller which half they got wrong."""
    client, _ = app_with_users
    missing = client.get(f"{API}/scans")
    malformed = client.get(f"{API}/scans", headers={"Authorization": "Bearer not-a-token"})
    assert missing.status_code == malformed.status_code == 401


def test_an_officer_cannot_manage_accounts(app_with_users):
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    response = client.get(f"{API}/auth/users", headers=officer)
    assert response.status_code == 403
    assert "ADMIN" in response.json()["detail"]


def test_an_administrator_can_create_an_officer(app_with_users):
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    response = client.post(
        f"{API}/auth/users",
        headers=admin,
        json={
            "email": "new.officer@metrology.gov.in",
            "full_name": "New Officer",
            "password": "graduation-tick-limit-line",
            "role": "SENIOR_OFFICER",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "SENIOR_OFFICER"
    assert "password" not in response.json()
    assert token_for(client, "new.officer@metrology.gov.in", "graduation-tick-limit-line")


def test_a_role_this_deployment_does_not_grant_is_refused(app_with_users):
    """An unassignable role in an authorisation check is a rule nobody can test."""
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    response = client.post(
        f"{API}/auth/users",
        headers=admin,
        json={
            "email": "maker@example.com",
            "full_name": "A Manufacturer",
            "password": "graduation-tick-limit-line",
            "role": "MANUFACTURER",
        },
    )
    assert response.status_code == 422


def test_a_weak_password_is_refused_at_the_api(app_with_users):
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    response = client.post(
        f"{API}/auth/users",
        headers=admin,
        json={
            "email": "weak@metrology.gov.in",
            "full_name": "Weak",
            "password": "short",
            "role": "SENIOR_OFFICER",
        },
    )
    assert response.status_code == 422
    assert "12 characters" in response.json()["detail"]


def test_a_duplicate_email_is_a_conflict(app_with_users):
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    payload = {
        "email": OFFICER_EMAIL,
        "full_name": "Duplicate",
        "password": "graduation-tick-limit-line",
        "role": "SENIOR_OFFICER",
    }
    assert client.post(f"{API}/auth/users", headers=admin, json=payload).status_code == 409


def test_an_administrator_cannot_lock_themselves_out(app_with_users):
    """The last administrator deactivating themselves leaves no way to grant the role."""
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    me = client.get(f"{API}/auth/me", headers=admin).json()
    response = client.post(f"{API}/auth/users/{me['id']}:deactivate", headers=admin)
    assert response.status_code == 409


def test_malformed_login_input_is_rejected(app_with_users):
    client, _ = app_with_users
    assert client.post(f"{API}/auth/login", json={"email": "not-an-email"}).status_code == 422
    assert client.post(f"{API}/auth/login", json={}).status_code == 422


# ----------------------------------------------------------------------- audit log


def test_signing_in_is_recorded(app_with_users):
    client, _ = app_with_users
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    entries = client.get(f"{API}/auth/audit", headers=admin, params={"entity_type": "user"}).json()
    assert any(e["action"] == "LOGIN" and e["actor_email"] == ADMIN_EMAIL for e in entries)


def test_a_failed_sign_in_is_recorded(app_with_users):
    """A run of these against one officer is something an administrator must be able
    to see afterwards."""
    client, _ = app_with_users
    client.post(f"{API}/auth/login", json={"email": OFFICER_EMAIL, "password": "wrong-password"})
    admin = auth(token_for(client, ADMIN_EMAIL, ADMIN_PASSWORD))
    entries = client.get(f"{API}/auth/audit", headers=admin).json()
    assert any(e["action"] == "LOGIN_FAILED" for e in entries)


def test_the_audit_trail_is_readable_by_any_officer(app_with_users):
    """A log only an administrator can read cannot be used to check an administrator."""
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    assert client.get(f"{API}/auth/audit", headers=officer).status_code == 200


def test_the_audit_trail_is_not_public(app_with_users):
    client, _ = app_with_users
    assert client.get(f"{API}/auth/audit").status_code == 401


# ------------------------------------------------------------------------ override


def _file_scan(client, headers):
    return client.post(
        f"{API}/scans",
        headers=headers,
        files=[("images", ("front.png", png(), "image/png"))],
        data={"product_name": "Roasted Chana Masala"},
    ).json()


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_an_override_never_erases_what_the_machine_decided(app_with_users, scripted):
    """The core invariant of this layer.

    The officer's decision becomes the finding's status; the automated verdict moves to
    `original_status` and is returned in every subsequent response. Both are visible,
    always.
    """
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    rule = "MRP_INCLUSIVE_OF_TAXES"

    before = next(f for f in scan["findings"] if f["rule_id"] == rule)
    assert before["status"] == FindingStatus.FAIL
    assert before["override"] is None

    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/{rule}:override",
        headers=officer,
        json={
            "status": "PASS",
            "reason": "Tax rider is printed on the reverse panel, verified on the pack in hand.",
        },
    )
    assert response.status_code == 200

    after = next(f for f in response.json()["findings"] if f["rule_id"] == rule)
    assert after["status"] == FindingStatus.PASS
    assert after["override"] is not None
    assert after["override"]["original_status"] == FindingStatus.FAIL
    assert "reverse panel" in after["override"]["reason"]
    assert after["override"]["overridden_by_id"]
    assert after["override"]["overridden_at"]

    # And it survives being reopened, which is where it actually matters.
    reopened = client.get(f"{API}/scans/{scan['scan_id']}", headers=officer).json()
    kept = next(f for f in reopened["findings"] if f["rule_id"] == rule)
    assert kept["override"]["original_status"] == FindingStatus.FAIL


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_a_second_override_still_records_the_machines_original(app_with_users, scripted):
    """A chain of revisions must not walk the original away one step at a time."""
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    rule = "MRP_INCLUSIVE_OF_TAXES"
    url = f"{API}/scans/{scan['scan_id']}/findings/{rule}:override"

    client.post(url, headers=officer, json={
        "status": "PASS", "reason": "Rider found on the reverse panel during inspection."
    })
    second = client.post(url, headers=officer, json={
        "status": "NEEDS_REVIEW", "reason": "Second look needed; the reverse text is ambiguous."
    })
    assert second.status_code == 200

    finding = next(f for f in second.json()["findings"] if f["rule_id"] == rule)
    assert finding["status"] == FindingStatus.NEEDS_REVIEW
    assert finding["override"]["original_status"] == FindingStatus.FAIL


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_an_override_is_audit_logged_with_its_reason(app_with_users, scripted):
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        headers=officer,
        json={"status": "PASS", "reason": "Rider printed on the reverse panel, verified."},
    )

    entries = client.get(
        f"{API}/auth/audit", headers=officer, params={"entity_type": "finding"}
    ).json()
    entry = next(e for e in entries if e["action"] == "FINDING_OVERRIDDEN")
    assert entry["actor_email"] == OFFICER_EMAIL
    assert entry["before"]["status"] == "FAIL"
    assert entry["after"]["status"] == "PASS"
    assert "reverse panel" in entry["after"]["reason"]


@pytest.mark.parametrize(
    "scripted",
    [[line for line in COMPLIANT_LINES if "inclusive of all taxes" not in line]],
    indirect=True,
)
def test_the_record_reports_both_where_it_stands_and_what_the_software_found(
    app_with_users, scripted
):
    """Neither verdict may hide the other.

    Reporting only the standing position would let a series of overrides quietly
    rewrite what the software found. Reporting only the automated one would leave a
    pack whose single failure an officer has resolved reading NON_COMPLIANT for good —
    which was the behaviour before this was split in two.
    """
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)

    assert scan["assessment"]["verdict"] == scan["assessment"]["automated_verdict"]
    assert scan["assessment"]["overridden"] == 0
    assert scan["assessment"]["failed"] == 1

    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_INCLUSIVE_OF_TAXES:override",
        headers=officer,
        json={
            "status": "PASS",
            "reason": "Tax rider is printed on the reverse panel, verified on the pack.",
        },
    )
    assessment = response.json()["assessment"]

    # The software's finding is preserved exactly as it was.
    assert assessment["automated_verdict"] == "NON_COMPLIANT"
    assert assessment["automated_score"] == scan["assessment"]["automated_score"]

    # And the record now stands where the officer left it: nothing failing any more.
    assert assessment["failed"] == 0
    assert assessment["verdict"] != "NON_COMPLIANT"
    assert assessment["overridden"] == 1

    reopened = client.get(f"{API}/scans/{scan['scan_id']}", headers=officer).json()
    assert reopened["assessment"] == assessment


def test_an_override_needs_a_real_reason(app_with_users, scripted):
    """"ok" recorded against a reversed violation is not a reason."""
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_PRESENT:override",
        headers=officer,
        json={"status": "FAIL", "reason": "ok"},
    )
    assert response.status_code == 422


def test_a_finding_cannot_be_overridden_to_not_applicable(app_with_users, scripted):
    """Whether a rule applies is a question about the statute, not a judgement call."""
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_PRESENT:override",
        headers=officer,
        json={"status": "NA", "reason": "This rule should not apply to this package."},
    )
    assert response.status_code == 422
    assert "exemption" in response.json()["detail"]


def test_overriding_a_finding_to_what_it_already_says_is_refused(app_with_users, scripted):
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    passing = next(f for f in scan["findings"] if f["status"] == FindingStatus.PASS)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/{passing['rule_id']}:override",
        headers=officer,
        json={"status": "PASS", "reason": "Agreeing with the automated finding here."},
    )
    assert response.status_code == 409


def test_an_anonymous_caller_cannot_override(app_with_users, scripted):
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/MRP_PRESENT:override",
        json={"status": "FAIL", "reason": "An anonymous override attempt, which must fail."},
    )
    assert response.status_code == 401


def test_overriding_a_rule_that_was_never_evaluated_is_a_404(app_with_users, scripted):
    client, _ = app_with_users
    officer = auth(token_for(client, OFFICER_EMAIL, OFFICER_PASSWORD))
    scan = _file_scan(client, officer)
    response = client.post(
        f"{API}/scans/{scan['scan_id']}/findings/NO_SUCH_RULE:override",
        headers=officer,
        json={"status": "FAIL", "reason": "Overriding a rule that does not exist here."},
    )
    assert response.status_code == 404
