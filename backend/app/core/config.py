"""Application settings, read from the environment (see infra/.env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Legal Metrology Compliance Bench"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    # SQLite by default so a clean checkout runs with no services; point at
    # postgresql+psycopg://... in infra/docker-compose.yml for the real deployment.
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'bench.db'}"

    # Storage for uploaded label photographs and generated reports.
    storage_dir: Path = REPO_ROOT / "data" / "storage"

    # Auth. jwt_secret MUST be overridden outside development.
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 8
    refresh_token_ttl_days: int = 14

    # Rules
    rules_dir: Path = REPO_ROOT / "rules"

    # Extraction
    ocr_lang: str = "en"
    # Which Extractor implementation the pipeline uses: "regex" (offline, deterministic)
    # or "hybrid" (regex first, VLM to fill gaps and judge semantic rules).
    extractor: str = "regex"
    anthropic_api_key: str | None = None
    vlm_model: str = "claude-sonnet-5"

    max_upload_mb: int = 25
    allowed_image_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")

    # --- retention ---------------------------------------------------------------
    # Days after an officer answers "no case is open" before the scan becomes eligible
    # for auto-deletion. This is the default; an administrator can override it at
    # runtime (see the retention settings endpoint), which is why the auto-delete job
    # reads the effective value rather than this constant directly.
    retention_days: int = 30

    # The auto-deletion job (Feature 6) also has a manual entry point,
    # `python -m app.cli prune-scans`, for deployments that drive it from a system
    # cron or a Kubernetes CronJob. When this is true the API process also runs it on
    # a timer while it is up, so a plain deployment needs no external scheduler. Set
    # false to leave it entirely to cron.
    retention_sweep_enabled: bool = True
    retention_sweep_interval_hours: float = 24.0
    # A short pause after boot before the first sweep, so a rolling restart does not
    # have every replica sweeping at once the instant it comes up.
    retention_sweep_initial_delay_seconds: float = 60.0

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite"):
        (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
