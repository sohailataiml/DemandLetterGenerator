"""The golden case: fixed dates, fixed data, one attorney template.

Everything here is deterministic on purpose. The conftest fixtures anchor to
"today" so the suite never trips the future-date rule; the golden case instead
pins every date, so a document generated from it can be compared against a
committed expectation without the comparison drifting each day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden_case"
TEMPLATE_PATH = FIXTURE_DIR / "template.docx"
EXPECTED_PATH = FIXTURE_DIR / "expected-demand.docx"
MATERIALS_DIR = FIXTURE_DIR / "case-materials"

LETTER_DATE = date(2025, 6, 6)
COLLISION_DATE = date(2024, 3, 4)
FIRST_VISIT = date(2024, 3, 7)
PAIN_MGMT_DATE = date(2024, 11, 15)
MRI_DATE = date(2024, 12, 21)
FOLLOW_UP_DATE = date(2025, 1, 12)
EXPIRES_AT = datetime(2025, 7, 6, 17, 0, tzinfo=timezone.utc)

ATTORNEY = {"X-User-Id": "attorney_45", "X-User-Role": "attorney"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _post(client, url, json, expect=201, headers=ATTORNEY):
    response = client.post(url, json=json, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


def _put(client, url, json, headers=ATTORNEY):
    response = client.put(url, json=json, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def seed_golden_case(client) -> dict:
    """Create the fixed case, upload the materials, verify the facts."""
    case = _post(
        client,
        "/v1/cases",
        {"reference": "GOLD-2025-0001", "client_display_name": "Patrick Donahue"},
    )
    case_id = case["id"]

    for full_name, roles, extra in [
        ("Patrick Donahue", [{"role": "client"}], {"email": "pd@example.test"}),
        (
            "Marisol Reyes",
            [{"role": "insured", "relationship_note": "Policyholder; vehicle owner."}],
            {},
        ),
        (
            "Andre Whitfield",
            [
                {
                    "role": "driver",
                    "relationship_note": "Son of the named insured; permissive user.",
                }
            ],
            {},
        ),
        ("Dana Okafor", [{"role": "attorney"}], {"email": "dokafor@example-firm.test"}),
    ]:
        _post(
            client,
            f"/v1/cases/{case_id}/parties",
            {"full_name": full_name, "roles": roles, **extra},
        )

    _put(
        client,
        f"/v1/cases/{case_id}/claim",
        {
            "claim_number": "017204635",
            "date_of_loss": COLLISION_DATE.isoformat(),
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
    _put(
        client,
        f"/v1/cases/{case_id}/accident",
        {
            "occurred_on": COLLISION_DATE.isoformat(),
            "location": "Vermont Ave and W 8th St, Los Angeles, CA",
            "description": "Rear-end collision while our client was stopped at a red light.",
            "impact_type": "rear-end",
        },
    )

    chiro = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "Vermont Spine and Injury", "provider_type": "chiropractic"},
    )
    imaging = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "MAX MRI Radiology", "provider_type": "imaging"},
    )
    pain = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "Harbor Pain Management", "provider_type": "pain management"},
    )

    for event_date, event_type, description, provider_id in [
        (FIRST_VISIT, "evaluation", "Initial chiropractic evaluation", chiro["id"]),
        (PAIN_MGMT_DATE, "consult", "Pain management evaluation", pain["id"]),
        (FOLLOW_UP_DATE, "follow_up", "Follow-up examination", pain["id"]),
    ]:
        _post(
            client,
            f"/v1/cases/{case_id}/treatment-events",
            {
                "event_date": event_date.isoformat(),
                "event_type": event_type,
                "description": description,
                "provider_id": provider_id,
            },
        )

    _post(
        client,
        f"/v1/cases/{case_id}/diagnoses",
        {
            "description": "Lumbar disc displacement",
            "code": "M51.26",
            "diagnosed_on": PAIN_MGMT_DATE.isoformat(),
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/imaging-findings",
        {
            "study_date": MRI_DATE.isoformat(),
            "modality": "MRI",
            "provider_id": imaging["id"],
            "body_region": "lumbar spine",
            "level": "L5-S1",
            "finding": "disc extrusion",
            "measurement": "9 x 10 x 5 mm",
        },
    )

    for provider_name, provider_id, payload in [
        ("Vermont Spine and Injury", chiro["id"], {"amount": "6480.00", "status": "KNOWN"}),
        ("MAX MRI Radiology", imaging["id"], {"amount": "3500.00", "status": "KNOWN"}),
        (
            "Harbor Pain Management",
            pain["id"],
            {
                "status": "PENDING",
                "description": "epidural steroid injection billing not yet received",
            },
        ),
    ]:
        _post(
            client,
            f"/v1/cases/{case_id}/bills",
            {"provider_name": provider_name, "provider_id": provider_id, **payload},
        )

    _post(
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
    _post(
        client,
        f"/v1/cases/{case_id}/damage-claims",
        {"category": "lost_wages", "description": "14 days missed work", "amount": "3120.00"},
    )
    _put(
        client,
        f"/v1/cases/{case_id}/settlement-terms",
        {
            "expires_at": EXPIRES_AT.isoformat(),
            "demand_type": "policy_limits",
            "demand_is_policy_limits": True,
            "delivery_method": "email",
        },
    )

    documents = {}
    for path in sorted(MATERIALS_DIR.glob("*.txt")):
        response = client.post(
            f"/v1/cases/{case_id}/documents",
            files={"file": (path.name, path.read_bytes(), "text/plain")},
            headers=ATTORNEY,
        )
        assert response.status_code == 201, response.text
        documents[path.name] = response.json()

    record_doc = documents["chiropractic-records.txt"]["id"]
    for fact_type, summary, value in GOLDEN_FACTS:
        fact = _post(
            client,
            f"/v1/cases/{case_id}/facts",
            {
                "fact_type": fact_type,
                "value": value,
                "summary": summary,
                "sources": [
                    {"document_id": record_doc, "page_number": 1, "excerpt": summary[:120]}
                ],
            },
        )
        response = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
        assert response.status_code == 200, response.text

    return {"case_id": case_id, "documents": documents, "reference": case["reference"]}


GOLDEN_FACTS = [
    (
        "liability",
        "Andre Whitfield struck the rear of the vehicle occupied by Patrick Donahue "
        "while it was stopped at a red light",
        {"basis": "police report narrative", "impact": "rear-end"},
    ),
    (
        "treatment_event",
        "Patrick Donahue treated with Vermont Spine and Injury beginning three days "
        "after the collision and continued through the following months",
        {"provider": "Vermont Spine and Injury"},
    ),
    (
        "diagnosis",
        "Treating providers diagnosed lumbar disc displacement",
        {"code": "M51.26"},
    ),
    (
        "imaging_finding",
        "MRI at MAX MRI Radiology showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
        {"level": "L5-S1", "finding": "disc extrusion"},
    ),
    (
        "functional_limitation",
        "Patrick Donahue reports interrupted sleep and an inability to lift his child "
        "without pain",
        {"limitations": ["sleep", "lifting"]},
    ),
]


def upload_template(client, case_id: str) -> dict:
    response = client.post(
        f"/v1/cases/{case_id}/templates",
        files={"file": ("template.docx", TEMPLATE_PATH.read_bytes(), DOCX_MIME)},
        data={"name": "Policy limits demand — firm standard"},
        headers=ATTORNEY,
    )
    assert response.status_code == 201, response.text
    return response.json()


def build_golden_demand(client) -> dict:
    """Seed, upload the template, bind it, generate. Returns the ids involved."""
    seeded = seed_golden_case(client)
    case_id = seeded["case_id"]
    template = upload_template(client, case_id)

    demand = _post(
        client,
        f"/v1/cases/{case_id}/demands",
        {"letter_date": LETTER_DATE.isoformat()},
    )
    response = client.post(
        f"/v1/demands/{demand['id']}/template",
        json={"template_id": template["id"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY
    )
    assert response.status_code == 200, response.text

    return {
        **seeded,
        "template_id": template["id"],
        "demand_id": demand["id"],
    }


def download_docx(client, demand_id: str) -> bytes:
    response = client.get(f"/v1/demands/{demand_id}/docx", headers=ATTORNEY)
    assert response.status_code == 200, response.text
    return response.content
