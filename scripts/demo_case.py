"""Seed a demo case and run the whole pipeline end to end.

    python scripts/demo_case.py                # built-in layout
    python scripts/demo_case.py --template     # bind the firm's .docx template
    python scripts/demo_case.py --extract      # AI-extract facts from materials

Runs entirely against the local SQLite database and filesystem storage — no
services to start, no containers. Prints the rendered letter, the validation
report and the readiness numbers, so the whole pipeline is visible in one go.

``--extract`` demonstrates that extracted facts arrive PROPOSED and are ignored
by generation until a human verifies them: the demo verifies its own facts
separately, and the extracted ones are left in the review queue on purpose.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ATTORNEY = {"X-User-Id": "attorney_demo", "X-User-Role": "attorney"}

TODAY = datetime.now(timezone.utc).date()
COLLISION = TODAY - timedelta(days=400)
FIRST_VISIT = COLLISION + timedelta(days=3)
PAIN_MGMT = COLLISION + timedelta(days=256)
MRI = COLLISION + timedelta(days=292)
EXPIRES = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=30)


def post(client, url, payload, expect=201):
    response = client.post(url, json=payload, headers=ATTORNEY)
    assert response.status_code == expect, f"{url} -> {response.status_code}: {response.text}"
    return response.json()


def put(client, url, payload):
    response = client.put(url, json=payload, headers=ATTORNEY)
    assert response.status_code == 200, f"{url} -> {response.status_code}: {response.text}"
    return response.json()


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEMPLATE_PATH = REPO_ROOT / "apps" / "api" / "tests" / "fixtures" / "golden_case" / "template.docx"
MATERIALS_DIR = REPO_ROOT / "apps" / "api" / "tests" / "fixtures" / "golden_case" / "case-materials"

#: A native-text PDF of the radiology report, and the passage on it that the
#: imaging fact quotes. Rebuild with ``python scripts/build_pdf_fixture.py``.
MRI_PDF_PATH = REPO_ROOT / "apps" / "api" / "tests" / "fixtures" / "provenance" / "mri-report.pdf"
MRI_FINDING_PAGE = 3
MRI_FINDING_QUOTE = (
    "Broad-based disc extrusion measuring 9 x 10 x 5 mm,\n"
    "extending into the right lateral recess with contact upon the\n"
    "traversing right S1 nerve root."
)


def upload_materials(client, case_id: str) -> list[dict]:
    """Upload the golden-case materials so extraction has something to read."""
    uploaded = []
    for path in sorted(MATERIALS_DIR.glob("*.txt")):
        response = client.post(
            f"/v1/cases/{case_id}/documents",
            files={"file": (path.name, path.read_bytes(), "text/plain")},
            headers=ATTORNEY,
        )
        if response.status_code == 201:
            uploaded.append(response.json())
    return uploaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template", action="store_true", help="bind the golden .docx template"
    )
    parser.add_argument(
        "--extract", action="store_true", help="run AI extraction over the case materials"
    )
    arguments = parser.parse_args()

    with TestClient(app) as client:
        reference = f"DEMO-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        case = post(
            client,
            "/v1/cases",
            {"reference": reference, "client_display_name": "Patrick Donahue"},
        )
        case_id = case["id"]
        print(f"case {case_id} ({reference})")

        for party in (
            {"full_name": "Patrick Donahue", "roles": [{"role": "client"}]},
            {
                "full_name": "Marisol Reyes",
                "roles": [{"role": "insured", "relationship_note": "Policyholder and owner."}],
            },
            {
                "full_name": "Andre Whitfield",
                "roles": [
                    {"role": "driver", "relationship_note": "Permissive user; son of the insured."}
                ],
            },
            {
                "full_name": "Dana Okafor",
                "roles": [{"role": "attorney"}],
                "email": "dokafor@example-firm.test",
            },
        ):
            post(client, f"/v1/cases/{case_id}/parties", party)

        put(
            client,
            f"/v1/cases/{case_id}/claim",
            {
                "claim_number": "017204635",
                "date_of_loss": COLLISION.isoformat(),
                "policy_number": "CA-88213",
                "policy_limit": "50000.00",
                "policy_limit_confirmed": True,
                "carrier": {
                    "name": "Meridian Casualty Insurance",
                    "adjuster_name": "T. Nakamura",
                    "address": "PO Box 4410\nPhoenix, AZ 85072",
                },
            },
        )
        put(
            client,
            f"/v1/cases/{case_id}/accident",
            {
                "occurred_on": COLLISION.isoformat(),
                "location": "Vermont Ave and W 8th St, Los Angeles, CA",
                "description": "Rear-end collision while our client was stopped at a red light.",
            },
        )

        chiro = post(
            client,
            f"/v1/cases/{case_id}/providers",
            {"name": "Vermont Spine and Injury", "provider_type": "chiropractic"},
        )
        radiology = post(
            client,
            f"/v1/cases/{case_id}/providers",
            {"name": "MAX MRI Radiology", "provider_type": "imaging"},
        )
        pain = post(
            client,
            f"/v1/cases/{case_id}/providers",
            {"name": "Harbor Pain Management", "provider_type": "pain management"},
        )

        post(
            client,
            f"/v1/cases/{case_id}/treatment-events",
            {
                "event_date": FIRST_VISIT.isoformat(),
                "event_type": "evaluation",
                "description": "Initial chiropractic evaluation",
                "provider_id": chiro["id"],
            },
        )
        post(
            client,
            f"/v1/cases/{case_id}/treatment-events",
            {
                "event_date": PAIN_MGMT.isoformat(),
                "event_type": "consult",
                "description": "Pain management evaluation",
                "provider_id": pain["id"],
            },
        )
        post(
            client,
            f"/v1/cases/{case_id}/imaging-findings",
            {
                "study_date": MRI.isoformat(),
                "modality": "MRI",
                "provider_id": radiology["id"],
                "body_region": "lumbar spine",
                "level": "L5-S1",
                "finding": "disc extrusion",
                "measurement": "9 x 10 x 5 mm",
            },
        )
        for bill in (
            {"provider_name": "Vermont Spine and Injury", "amount": "6480.00", "status": "KNOWN"},
            {"provider_name": "MAX MRI Radiology", "amount": "3500.00", "status": "KNOWN"},
            {
                "provider_name": "Harbor Pain Management",
                "status": "PENDING",
                "description": "injection billing not yet received",
            },
        ):
            post(client, f"/v1/cases/{case_id}/bills", bill)
        post(
            client,
            f"/v1/cases/{case_id}/future-treatments",
            {
                "description": "Lumbar epidural steroid injection series",
                "provider_name": "Harbor Pain Management",
                "quantity": 2,
                "cost_low": "4200.00",
                "cost_high": "5600.00",
            },
        )
        put(
            client,
            f"/v1/cases/{case_id}/settlement-terms",
            {"expires_at": EXPIRES.isoformat(), "demand_is_policy_limits": True},
        )

        upload = client.post(
            f"/v1/cases/{case_id}/documents",
            files={
                "file": (
                    "records.txt",
                    b"Provider: Vermont Spine and Injury\nLumbar pain following the collision.",
                    "text/plain",
                )
            },
            headers=ATTORNEY,
        )
        document_id = upload.json()["id"]

        # The radiology report goes in as a real PDF so the imaging fact below
        # cites a page an attorney can open and see highlighted, rather than a
        # transcript of one.
        mri = client.post(
            f"/v1/cases/{case_id}/documents",
            files={"file": ("mri-report.pdf", MRI_PDF_PATH.read_bytes(), "application/pdf")},
            data={"document_type": "MRI_REPORT", "provider_name": "MAX MRI Radiology"},
            headers=ATTORNEY,
        )
        assert mri.status_code == 201, mri.text
        mri_document_id = mri.json()["id"]

        for fact_type, summary, citation in (
            (
                "liability",
                "Andre Whitfield struck the rear of the vehicle occupied by Patrick Donahue while it was stopped at a red light",
                {"document_id": document_id, "page_number": 1},
            ),
            (
                "treatment_event",
                "Patrick Donahue treated with Vermont Spine and Injury and later with Harbor Pain Management",
                {"document_id": document_id, "page_number": 1},
            ),
            (
                "diagnosis",
                "Treating providers diagnosed lumbar disc displacement",
                {"document_id": document_id, "page_number": 1},
            ),
            (
                "imaging_finding",
                "MRI at MAX MRI Radiology showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
                {
                    "document_id": mri_document_id,
                    "page_number": MRI_FINDING_PAGE,
                    "excerpt": MRI_FINDING_QUOTE,
                },
            ),
            (
                "functional_limitation",
                "Patrick Donahue reports interrupted sleep and difficulty lifting without pain",
                {"document_id": document_id, "page_number": 1},
            ),
        ):
            fact = post(
                client,
                f"/v1/cases/{case_id}/facts",
                {
                    "fact_type": fact_type,
                    "value": {"note": summary},
                    "summary": summary,
                    "sources": [citation],
                },
            )
            client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
            if fact_type == "imaging_finding":
                citation_record = fact["sources"][0]
                print()
                print(
                    f"imaging fact {fact['id']} cites {mri_document_id} "
                    f"page {citation_record['page_number']}: "
                    f"{citation_record['citation_status']} with "
                    f"{len(citation_record['bounding_boxes'] or [])} highlight box(es)"
                )

        if arguments.extract:
            materials = upload_materials(client, case_id)
            reports = post(client, f"/v1/cases/{case_id}/extract", {}, expect=202)
            proposed = sum(report["proposed"] for report in reports)
            rejected = sum(len(report["rejected"]) for report in reports)
            flagged = sum(len(report["suspected_injection_chunks"]) for report in reports)
            print()
            print(
                f"extraction: {len(materials)} document(s) read, "
                f"{proposed} fact(s) PROPOSED, "
                f"{rejected} candidate(s) rejected for an unresolvable citation, "
                f"{flagged} chunk(s) containing instruction-shaped text"
            )
            print("  none of them are verified — they are waiting for a human.")

        demand = post(client, f"/v1/cases/{case_id}/demands", {})

        if arguments.template:
            with TEMPLATE_PATH.open("rb") as handle:
                response = client.post(
                    f"/v1/cases/{case_id}/templates",
                    files={"file": ("template.docx", handle.read(), DOCX_MIME)},
                    data={"name": "Firm standard demand"},
                    headers=ATTORNEY,
                )
            assert response.status_code == 201, response.text
            template = response.json()
            print()
            print(
                f"template {template['id']} — {template['block_count']} blocks, "
                f"{len(template['slots'])} dynamic slots, "
                f"headers {template['header_parts']}, footers {template['footer_parts']}"
            )
            bound = client.post(
                f"/v1/demands/{demand['id']}/template",
                json={"template_id": template["id"]},
                headers=ATTORNEY,
            )
            assert bound.status_code == 200, bound.text

        demand = post(
            client, f"/v1/demands/{demand['id']}/generate", {}, expect=200
        )

        print("\n" + "=" * 78)
        for section in demand["sections"]:
            print(f"\n--- {section['title'].upper()}  [{section['source']}]")
            print(section["body"])
        print("\n" + "=" * 78)

        issues = client.post(
            f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY
        ).json()
        print(f"\nvalidation: {len(issues)} issue(s)")
        for issue in issues:
            print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")

        detail = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()
        if detail.get("claim_report"):
            claims = detail["claim_report"]
            print()
            print(
                f"claim grounding: {claims['claims_checked']} claim(s) checked, "
                f"{claims['supported']} supported, {claims['unsupported']} unsupported"
            )
        if detail.get("fidelity_report"):
            fidelity = detail["fidelity_report"]
            blocks = fidelity["required_blocks"]
            print(
                f"template fidelity: {blocks['preserved']}/{blocks['expected']} required blocks "
                f"preserved, {fidelity['styles_changed']} style change(s), "
                f"{fidelity['headers_changed']} header change(s), "
                f"{fidelity['footers_changed']} footer change(s)"
            )

        blocking = [i for i in issues if i["severity"] == "BLOCKING"]
        if not blocking:
            approved = client.post(
                f"/v1/demands/{demand['id']}/approve",
                json={"acknowledgement": reference},
                headers=ATTORNEY,
            ).json()
            print(f"\napproved by {approved['approved_by']}, docx sha256 {approved['docx_sha256']}")

        docx = client.get(f"/v1/demands/{demand['id']}/docx", headers=ATTORNEY)
        out = REPO_ROOT / "var" / f"demand-{reference}.docx"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(docx.content)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
