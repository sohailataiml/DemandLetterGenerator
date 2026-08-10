"""Role-based access control on the mutating paths."""

from __future__ import annotations

from conftest import ATTORNEY, PARALEGAL, READONLY


def test_credentials_are_required(client):
    response = client.post("/v1/cases", json={"reference": "X-1", "client_display_name": "A"})
    assert response.status_code == 401


def test_unknown_role_is_rejected(client):
    response = client.post(
        "/v1/cases",
        json={"reference": "X-1", "client_display_name": "A"},
        headers={"X-User-Id": "u1", "X-User-Role": "auditor"},
    )
    assert response.status_code == 401
    assert "unknown role" in response.json()["detail"]


def test_readonly_can_read_but_not_write(client, seeded_case):
    case_id = seeded_case["case_id"]
    assert client.get(f"/v1/cases/{case_id}", headers=READONLY).status_code == 200
    assert client.get(f"/v1/cases/{case_id}/damages", headers=READONLY).status_code == 200

    response = client.post(
        f"/v1/cases/{case_id}/bills",
        json={"provider_name": "Someone", "amount": "1.00"},
        headers=READONLY,
    )
    assert response.status_code == 403


def test_paralegal_can_build_the_case_but_not_approve(client, seeded_case):
    case_id = seeded_case["case_id"]
    response = client.post(
        f"/v1/cases/{case_id}/bills",
        json={"provider_name": "Radiology Partners", "amount": "125.00"},
        headers=PARALEGAL,
    )
    assert response.status_code == 201

    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=PARALEGAL).json()
    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case["reference"]},
        headers=PARALEGAL,
    )
    assert response.status_code == 403


def test_admin_inherits_every_permission(client, seeded_case):
    admin = {"X-User-Id": "root", "X-User-Role": "admin"}
    response = client.post(
        f"/v1/cases/{seeded_case['case_id']}/bills",
        json={"provider_name": "Anywhere Clinic", "amount": "10.00"},
        headers=admin,
    )
    assert response.status_code == 201


def test_health_is_open(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "stub"
    assert body["anthropic_configured"] is False
