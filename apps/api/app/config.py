"""Runtime configuration.

Deliberately dependency-free (no pydantic-settings) so the service boots from a
bare environment. Every value has a development default; anything that would be
unsafe in production (auth mode, storage root) is called out in the README.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return int(raw)


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return list(default)
    return [part.strip() for part in raw.split("|") if part.strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_root: Path
    #: Create tables from the models at startup. Convenient for a first run;
    #: turn it off in a deployment so a missing migration is visible.
    auto_create_schema: bool
    max_upload_bytes: int
    allowed_upload_mime: frozenset[str]

    # Background work. "thread" runs jobs on a worker thread of this process;
    # "inline" runs them synchronously (tests). See app/jobs/runner.py for the
    # limits of both and what a multi-process deployment needs instead.
    job_runner: str

    # AI layer
    llm_provider: str
    extraction_provider: str
    anthropic_model: str
    anthropic_api_key: str | None
    anthropic_effort: str

    # Letterhead / firm identity used by the deterministic template blocks.
    firm_name: str
    firm_address_lines: list[str] = field(default_factory=list)
    firm_phone: str = ""
    firm_email: str = ""

    # Browser origins allowed to call the API. Explicit list, never a wildcard.
    cors_origins: list[str] = field(default_factory=list)

    @property
    def is_anthropic_enabled(self) -> bool:
        return self.llm_provider == "anthropic" and bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    storage_root = Path(_env("DLG_STORAGE_ROOT", str(REPO_ROOT / "var" / "storage")))
    return Settings(
        database_url=_env("DLG_DATABASE_URL", f"sqlite:///{REPO_ROOT / 'var' / 'demand.db'}"),
        storage_root=storage_root,
        auto_create_schema=_env_bool("DLG_AUTO_CREATE_SCHEMA", True),
        max_upload_bytes=_env_int("DLG_MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
        allowed_upload_mime=frozenset(
            {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
                "image/jpeg",
                "image/png",
                "text/plain",
                "text/markdown",
            }
        ),
        job_runner=_env("DLG_JOB_RUNNER", "thread"),
        llm_provider=_env("DLG_LLM_PROVIDER", "stub"),
        extraction_provider=_env("DLG_EXTRACTION_PROVIDER", "pattern"),
        anthropic_model=_env("DLG_ANTHROPIC_MODEL", "claude-opus-5"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_effort=_env("DLG_ANTHROPIC_EFFORT", "high"),
        firm_name=_env("DLG_FIRM_NAME", "Stalwart Law Group"),
        firm_address_lines=_env_list(
            "DLG_FIRM_ADDRESS",
            ["1055 W 7th St, Suite 2800", "Los Angeles, CA 90017"],
        ),
        firm_phone=_env("DLG_FIRM_PHONE", "(213) 000-0000"),
        firm_email=_env("DLG_FIRM_EMAIL", "claims@example-firm.test"),
        cors_origins=_env_list(
            "DLG_CORS_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]
        ),
    )
