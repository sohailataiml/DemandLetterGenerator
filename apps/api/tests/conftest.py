"""Test fixtures.

Environment variables are set before any application import so the engine and
object store bind to a throwaway directory rather than the developer's data.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="dlg-tests-"))
os.environ["DLG_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["DLG_STORAGE_ROOT"] = str(_TMP / "storage")
os.environ["DLG_LLM_PROVIDER"] = "stub"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Dates are anchored to "today" so the suite never trips the future-date rule.
TODAY = datetime.now(timezone.utc).date()
COLLISION_DATE = TODAY - timedelta(days=400)
FIRST_VISIT = COLLISION_DATE + timedelta(days=3)
PAIN_MGMT_DATE = COLLISION_DATE + timedelta(days=256)
MRI_DATE = COLLISION_DATE + timedelta(days=292)
FOLLOW_UP_DATE = COLLISION_DATE + timedelta(days=314)
EXPIRES_AT = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=30)

ATTORNEY = {"X-User-Id": "attorney_45", "X-User-Role": "attorney"}
PARALEGAL = {"X-User-Id": "para_7", "X-User-Role": "paralegal"}
READONLY = {"X-User-Id": "viewer_1", "X-User-Role": "readonly"}


@pytest.fixture(autouse=True)
def fresh_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _post(client, url, json, headers=ATTORNEY, expect=201):
    response = client.post(url, json=json, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


@pytest.fixture
def seeded_case(client) -> dict:
    """A complete case: parties, claim, accident, treatment, bills, terms.

    Deliberately mirrors the shape of the supplied demand letter — including a
    named insured who is *not* the driver, and one bill whose amount has not
    arrived yet.
    """
    case = _post(
        client,
        "/v1/cases",
        {"reference": "PD-2025-0142", "client_display_name": "Patrick Donahue"},
    )
    case_id = case["id"]

    client_party = _post(
        client,
        f"/v1/cases/{case_id}/parties",
        {"full_name": "Patrick Donahue", "roles": [{"role": "client"}], "email": "pd@example.test"},
    )
    _post(
        client,
        f"/v1/cases/{case_id}/parties",
        {
            "full_name": "Marisol Reyes",
            "roles": [
                {"role": "insured", "relationship_note": "Policyholder; vehicle owner."},
            ],
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/parties",
        {
            "full_name": "Andre Whitfield",
            "roles": [
                {
                    "role": "driver",
                    "relationship_note": "Son of the named insured; permissive user at the time of the collision.",
                }
            ],
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/parties",
        {
            "full_name": "Dana Okafor",
            "roles": [{"role": "attorney"}],
            "email": "dokafor@example-firm.test",
        },
    )

    response = client.put(
        f"/v1/cases/{case_id}/claim",
        json={
            "claim_number": "017204635",
            "date_of_loss": COLLISION_DATE.isoformat(),
            "policy_number": "CA-88213",
            "policy_limit": "50000.00",
            "policy_limit_confirmed": True,
            "carrier": {
                "name": "Meridian Casualty Insurance",
                "adjuster_name": "T. Nakamura",
                "adjuster_email": "tnakamura@example-carrier.test",
                "address": "PO Box 4410\nPhoenix, AZ 85072",
            },
        },
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text

    response = client.put(
        f"/v1/cases/{case_id}/accident",
        json={
            "occurred_on": COLLISION_DATE.isoformat(),
            "location": "Vermont Ave and W 8th St, Los Angeles, CA",
            "description": "Rear-end collision while our client was stopped at a red light.",
            "impact_type": "rear-end",
        },
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text

    chiro = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "Vermont Spine and Injury", "provider_type": "chiropractic"},
    )
    imaging_provider = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "MAX MRI Radiology", "provider_type": "imaging"},
    )
    pain_mgmt = _post(
        client,
        f"/v1/cases/{case_id}/providers",
        {"name": "Harbor Pain Management", "provider_type": "pain management"},
    )

    _post(
        client,
        f"/v1/cases/{case_id}/treatment-events",
        {
            "event_date": FIRST_VISIT.isoformat(),
            "event_type": "evaluation",
            "description": "Initial chiropractic evaluation",
            "provider_id": chiro["id"],
            "body_regions": ["cervical spine", "lumbar spine"],
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/treatment-events",
        {
            "event_date": PAIN_MGMT_DATE.isoformat(),
            "event_type": "consult",
            "description": "Pain management evaluation",
            "provider_id": pain_mgmt["id"],
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/treatment-events",
        {
            "event_date": FOLLOW_UP_DATE.isoformat(),
            "event_type": "follow_up",
            "description": "Follow-up examination",
            "provider_id": pain_mgmt["id"],
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
            "provider_id": imaging_provider["id"],
            "body_region": "lumbar spine",
            "level": "L5-S1",
            "finding": "disc extrusion",
            "measurement": "9 x 10 x 5 mm",
        },
    )

    _post(
        client,
        f"/v1/cases/{case_id}/bills",
        {
            "provider_name": "Vermont Spine and Injury",
            "provider_id": chiro["id"],
            "amount": "6480.00",
            "status": "KNOWN",
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/bills",
        {
            "provider_name": "MAX MRI Radiology",
            "provider_id": imaging_provider["id"],
            "amount": "3500.00",
            "status": "KNOWN",
        },
    )
    _post(
        client,
        f"/v1/cases/{case_id}/bills",
        {
            "provider_name": "Harbor Pain Management",
            "provider_id": pain_mgmt["id"],
            "status": "PENDING",
            "description": "epidural steroid injection billing not yet received",
        },
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

    response = client.put(
        f"/v1/cases/{case_id}/settlement-terms",
        json={
            "expires_at": EXPIRES_AT.isoformat(),
            "demand_type": "policy_limits",
            "demand_is_policy_limits": True,
            "delivery_method": "email",
        },
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text

    return {
        "case_id": case_id,
        "reference": case["reference"],
        "client_party_id": client_party["id"],
        "providers": {
            "chiro": chiro["id"],
            "imaging": imaging_provider["id"],
            "pain": pain_mgmt["id"],
        },
    }


def upload_text_document(client, case_id: str, name: str, body: str, headers=ATTORNEY):
    response = client.post(
        f"/v1/cases/{case_id}/documents",
        files={"file": (name, body.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def verify_new_fact(client, case_id: str, document_id: str, fact_type: str, summary: str, value: dict):
    """Propose and verify a fact in one step, the way a paralegal would."""
    fact = _post(
        client,
        f"/v1/cases/{case_id}/facts",
        {
            "fact_type": fact_type,
            "value": value,
            "summary": summary,
            "sources": [{"document_id": document_id, "page_number": 1, "excerpt": summary[:120]}],
        },
    )
    response = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def seeded_case_with_facts(client, seeded_case) -> dict:
    case_id = seeded_case["case_id"]
    doc = upload_text_document(
        client,
        case_id,
        "records-summary.txt",
        "Provider: Vermont Spine and Injury\nPatient reports lumbar pain following the collision.",
    )
    seeded_case["document_id"] = doc["id"]

    verify_new_fact(
        client,
        case_id,
        doc["id"],
        "liability",
        "Andre Whitfield struck the rear of the vehicle occupied by Patrick Donahue while it was stopped at a red light",
        {"basis": "police report narrative", "impact": "rear-end"},
    )
    verify_new_fact(
        client,
        case_id,
        doc["id"],
        "treatment_event",
        "Patrick Donahue treated with Vermont Spine and Injury beginning three days after the collision and continued through the following months",
        {"provider": "Vermont Spine and Injury"},
    )
    verify_new_fact(
        client,
        case_id,
        doc["id"],
        "diagnosis",
        "Treating providers diagnosed lumbar disc displacement",
        {"code": "M51.26"},
    )
    verify_new_fact(
        client,
        case_id,
        doc["id"],
        "imaging_finding",
        "MRI at MAX MRI Radiology showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
        {"level": "L5-S1", "finding": "disc extrusion", "measurement": "9 x 10 x 5 mm"},
    )
    verify_new_fact(
        client,
        case_id,
        doc["id"],
        "functional_limitation",
        "Patrick Donahue reports interrupted sleep and an inability to lift his child without pain",
        {"limitations": ["sleep", "lifting"]},
    )
    return seeded_case
