"""Regenerates ``expected-demand.docx`` by running the real pipeline.

    python scripts/build_golden_expected.py

Run this only when the golden expectation should legitimately change — a new
template, a deliberate change to how a slot is bound. The test that reads the
file is a regression test: if it fails and you have not changed the pipeline on
purpose, the pipeline is what is wrong, not the fixture.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "tests"))

_TMP = Path(tempfile.mkdtemp(prefix="dlg-golden-"))
os.environ["DLG_DATABASE_URL"] = f"sqlite:///{_TMP / 'golden.db'}"
os.environ["DLG_STORAGE_ROOT"] = str(_TMP / "storage")
os.environ["DLG_LLM_PROVIDER"] = "stub"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import golden  # noqa: E402  (apps/api/tests)
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        built = golden.build_golden_demand(client)
        data = golden.download_docx(client, built["demand_id"])
    golden.EXPECTED_PATH.write_bytes(data)
    print(f"wrote {golden.EXPECTED_PATH.relative_to(REPO_ROOT)} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
