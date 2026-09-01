"""A migrated database, an app on it, and accounts to sign in with.

Shared by the repository and auth suites so both exercise the same wiring an operator
would get: schema built by migrations, users created through the real hashing path.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.core.db import get_db
from app.core.security import hash_password
from app.main import create_app
from app.models.enums import Role
from app.models.tables import User
from tests.test_migrations import _alembic_config as alembic_config

API = "/api/v1"

# Long enough to clear the twelve-character floor, and obviously not a real secret.
ADMIN_PASSWORD = "vernier-caliper-brass-0001"
OFFICER_PASSWORD = "beam-balance-tare-weight-02"


def build_app(tmp_path, monkeypatch) -> tuple[TestClient, sessionmaker]:
    monkeypatch.setattr("app.core.config.settings.storage_dir", tmp_path / "storage")
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setattr("app.core.config.settings.database_url", url)
    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override() -> Iterator:
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override
    return TestClient(app), Session


def seed_user(
    Session: sessionmaker,
    *,
    email: str,
    password: str,
    role: Role,
    is_active: bool = True,
) -> str:
    """Create an account the way the application would, hash included."""
    db = Session()
    try:
        user = User(
            email=email,
            full_name=email.split("@")[0].replace(".", " ").title(),
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def token_for(client: TestClient, email: str, password: str) -> str:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
