"""Build the native-text PDF the provenance tests and the demo read.

    python scripts/build_pdf_fixture.py

The output is committed, so neither the test suite nor the demo needs a PDF
writer installed. Regenerate it only when the fixture text changes — the tests
assert against the words on the page, not against the bytes.

The report is laid out over three pages on purpose: the finding an attorney
would cite sits on page 3, and its sentence wraps across three lines, so the
demo exercises both "open the right page" and "highlight a passage that is not a
single rectangle".
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "apps" / "api" / "tests" / "fixtures" / "provenance" / "mri-report.pdf"

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
MARGIN = 72.0
LEADING = 16.0

PAGES: list[list[tuple[str, str]]] = [
    [
        ("title", "MAX MRI RADIOLOGY"),
        ("body", "1450 Vermont Avenue, Los Angeles, CA 90027"),
        ("gap", ""),
        ("heading", "PATIENT"),
        ("body", "Patient: Patrick Donahue"),
        ("body", "Study Date: December 21, 2024"),
        ("body", "Examination: MRI LUMBAR SPINE WITHOUT CONTRAST"),
        ("body", "Referring Provider: Vermont Spine and Injury"),
        ("gap", ""),
        ("heading", "CLINICAL HISTORY"),
        ("body", "Low back pain with right lower extremity radiation following a"),
        ("body", "motor vehicle collision. Conservative care without resolution."),
    ],
    [
        ("heading", "TECHNIQUE"),
        ("body", "Multiplanar, multisequence imaging of the lumbar spine was"),
        ("body", "performed without intravenous contrast. Sagittal T1, sagittal T2,"),
        ("body", "and axial T2 sequences were obtained."),
        ("gap", ""),
        ("heading", "COMPARISON"),
        ("body", "No prior lumbar imaging is available for comparison."),
        ("gap", ""),
        ("heading", "ALIGNMENT"),
        ("body", "Lumbar lordosis is preserved. Vertebral body heights are"),
        ("body", "maintained. No fracture or spondylolisthesis is identified."),
    ],
    [
        ("heading", "FINDINGS"),
        ("body", "L5-S1: Broad-based disc extrusion measuring 9 x 10 x 5 mm,"),
        ("body", "extending into the right lateral recess with contact upon the"),
        ("body", "traversing right S1 nerve root."),
        ("body", "L4-L5: Mild disc bulge without stenosis."),
        ("body", "L3-L4: Unremarkable."),
        ("gap", ""),
        ("heading", "IMPRESSION"),
        ("body", "1. L5-S1 disc extrusion with right S1 nerve root contact."),
        ("body", "2. Findings correlate with the reported right lower extremity"),
        ("body", "symptoms."),
        ("gap", ""),
        ("body", "Electronically signed by R. Adeyemi, M.D."),
    ],
]

STYLES = {
    "title": ("hebo", 16.0),
    "heading": ("hebo", 12.0),
    "body": ("helv", 11.0),
    "gap": ("helv", 11.0),
}


def build() -> Path:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - developer tooling
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError:
            print("PyMuPDF is required to rebuild this fixture: pip install pymupdf")
            raise SystemExit(1)

    document = pymupdf.open()
    for lines in PAGES:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN + 20
        for style, text in lines:
            font, size = STYLES[style]
            if text:
                page.insert_text((MARGIN, y), text, fontname=font, fontsize=size)
            y += LEADING if style != "title" else LEADING + 8

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT, deflate=True)
    document.close()
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size} bytes)")
    sys.exit(0)
