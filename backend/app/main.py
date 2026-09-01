"""The API.

Wires the tested pipeline to HTTP and adds nothing to its reasoning. Every judgement in
a response was made in `app.rules.engine`; this layer decodes uploads, hands them over,
and reports what came back.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, dashboard, images, meta, reports, scans
from app.core.config import settings
from app.core.security import DEFAULT_DEV_SECRET
from app.rules.loader import RulesetContractError, available_versions
from app.services import retention_scheduler
from app.services.imaging import ScanInputError

log = logging.getLogger(__name__)

DESCRIPTION = """
Checks packaged commodities against the Legal Metrology (Packaged Commodities)
Rules, 2011.

This is decision support, not a legal determination. Every finding carries the rule it
came from and the evidence it was decided on, and anything the images could not settle
is returned as NEEDS_REVIEW for an officer rather than as a violation.
""".strip()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    # The web client is served from a different origin. Locked to a named list
    # (settings.cors_origins) rather than "*", so this does not quietly ship as an
    # open API — the deployed frontend URL has to be added explicitly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(meta.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(scans.router, prefix=settings.api_prefix)
    app.include_router(reports.router, prefix=settings.api_prefix)
    app.include_router(dashboard.router, prefix=settings.api_prefix)
    app.include_router(images.router, prefix=settings.api_prefix)
    app.include_router(images.revisions_router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)

    @app.exception_handler(ScanInputError)
    async def _bad_input(_: Request, exc: ScanInputError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.on_event("startup")
    def _check_rulesets() -> None:
        """Fail loudly at boot rather than on the first scan.

        `available_versions` loads and contract-validates every ruleset on disk. A rule
        naming an attribute its declaration does not have would otherwise surface as a
        500 on an officer's first upload.
        """
        versions = available_versions()
        log.info("Rulesets loaded: %s", ", ".join(versions))

    @app.on_event("startup")
    def _check_signing_secret() -> None:
        """Refuse to run outside development on the checked-in signing secret.

        The default secret is in the repository. A server signing tokens with it is one
        where anyone holding a copy of the source can mint an ADMIN token — which is
        every developer, and anyone the code was ever shared with. This has to be a
        refusal rather than a warning: a warning in a startup log is exactly what a
        deployment misses.
        """
        if settings.jwt_secret != DEFAULT_DEV_SECRET:
            return
        if settings.is_dev:
            log.warning(
                "Signing tokens with the development secret. Set JWT_SECRET before "
                "this server is reachable by anyone else."
            )
            return
        raise RuntimeError(
            f"JWT_SECRET is still the development default in environment "
            f"{settings.environment!r}. Set it to a long random value before starting."
        )

    # Feature 6: the retention auto-deletion job runs on a timer while the API is up
    # (unless retention_sweep_enabled is false, in which case a cron drives
    # `app.cli prune-scans` instead).
    retention_scheduler.attach(app)

    return app


try:
    app = create_app()
except RulesetContractError:  # pragma: no cover - a broken ruleset must not boot
    log.exception("A ruleset on disk does not match the declarations it judges.")
    raise
