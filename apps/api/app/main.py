from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.v1 import router as v1_router
from .config import get_settings
from .db import create_all

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Development convenience. Production should run Alembic migrations instead.
    create_all()
    settings = get_settings()
    logger.info("storage_root=%s llm_provider=%s", settings.storage_root, settings.llm_provider)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Demand Letter Generation and Review",
    version=__version__,
    description=(
        "Assembles personal injury demand letters from attorney-verified facts. "
        "AI drafts narrative prose only; totals, dates, and claim metadata are "
        "computed deterministically and validated before any draft can be approved."
    ),
)

_settings = get_settings()
if _settings.cors_origins:
    # Explicit dev origins only. Credentials stay off: the client authenticates
    # with headers, not cookies, so there is nothing for a browser to attach
    # automatically to a cross-site request.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["X-User-Id", "X-User-Role", "Content-Type", "Accept"],
        expose_headers=["X-Content-SHA256", "Content-Disposition"],
    )

app.include_router(v1_router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness for this service only.

    Deliberately makes no network call. Whether the Secure AI Gateway is
    *configured* is local knowledge and useful here; whether it is *reachable*
    is a separate question answered by ``/v1/ai-boundary``, because a demand
    letter service that cannot draft can still be read, validated, approved and
    downloaded, and reporting it as unhealthy would be wrong.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_provider": settings.llm_provider,
        "anthropic_configured": settings.is_anthropic_enabled,
        "secure_gateway_configured": settings.is_secure_gateway_configured,
    }
