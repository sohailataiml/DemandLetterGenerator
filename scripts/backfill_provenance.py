"""Backfill page geometry and citation precision for documents already on file.

    python scripts/backfill_provenance.py            # every case
    python scripts/backfill_provenance.py --case-id case_...
    python scripts/backfill_provenance.py --dry-run  # report, change nothing

Safe to run repeatedly. It never re-extracts a document's text and never touches
a fact, so a verified fact means exactly what it meant before — the only thing
that improves is how precisely the system can show where it came from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.db import SessionLocal  # noqa: E402
from app.provenance import backfill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default=None, help="limit the run to one case")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, then roll back"
    )
    arguments = parser.parse_args()

    session = SessionLocal()
    try:
        report = backfill.run(session, case_id=arguments.case_id)
        if arguments.dry_run:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()

    print("documents")
    print(f"  examined            {report.documents_examined}")
    print(f"  with geometry       {report.documents_with_geometry}")
    print(f"  pages geo-indexed   {report.pages_with_geometry}")
    print(f"  pages unalignable   {report.pages_unalignable}")
    print("citations")
    print(f"  examined            {report.citations_examined}")
    print(f"  exact               {report.exact}")
    print(f"  ambiguous           {report.ambiguous}")
    print(f"  text only           {report.text_only}")
    print(f"  unresolved          {report.unresolved}")
    print(f"  newly exact         {report.exact_upgraded}")
    print(f"  boxes added         {report.boxes_added}")
    for note in report.notes:
        print(f"  note: {note}")
    if arguments.dry_run:
        print("\ndry run - nothing was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
