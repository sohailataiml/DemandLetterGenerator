"""Seed one demo case, but only when the database has none.

    python scripts/seed_if_empty.py

Written for the deployed demo, where storage is ephemeral: every deploy starts
with an empty disk, and an empty case list is a bad first screen. Running this
before the server starts means a fresh instance is immediately usable.

It is a no-op when a case already exists, so restarting a service does not
accumulate duplicates. It is also a no-op unless ``DLG_DEMO_SEED`` is set,
so it can sit in a start command without affecting a real environment that
happens to boot with an empty database.

Failure here is deliberately non-fatal. A demo without a seeded case is worth
more than a service that will not start.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def _enabled() -> bool:
    return os.environ.get("DLG_DEMO_SEED", "").strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    if not _enabled():
        print("seed: DLG_DEMO_SEED is not set — skipping")
        return 0

    from sqlalchemy import func, select

    from app.db import create_all, session_scope
    from app.domain.models import Case

    create_all()

    with session_scope() as session:
        existing = session.scalar(select(func.count()).select_from(Case)) or 0
    if existing:
        print(f"seed: {existing} case(s) already present — skipping")
        return 0

    print("seed: empty database, creating the demo case…")
    try:
        import demo_case  # noqa: PLC0415  (scripts/ is on sys.path below)
    except ImportError:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import demo_case  # type: ignore[no-redef]

    try:
        # The full pipeline: template binding and extraction included, so the
        # deployed demo shows the same thing the README describes.
        sys.argv = ["demo_case.py", "--template", "--extract"]
        demo_case.main()
    except Exception:  # noqa: BLE001 — never block startup on the seed
        print("seed: demo case failed; the service will start with no cases", file=sys.stderr)
        traceback.print_exc()
        return 0

    print("seed: demo case created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
