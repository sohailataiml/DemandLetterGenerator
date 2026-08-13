"""The golden case, end to end, against a committed expected document.

``expected-demand.docx`` was produced by ``scripts/build_golden_expected.py``
running this exact pipeline. If this test fails and the pipeline was not
changed on purpose, the pipeline is what regressed — regenerate the fixture
only when the new output is the output you meant to produce.
"""

from __future__ import annotations

import docx_compare
import golden
from app.templates import analyzer, fidelity


def test_golden_demand_matches_the_expected_document(client):
    built = golden.build_golden_demand(client)
    actual = golden.download_docx(client, built["demand_id"])
    docx_compare.assert_matches(golden.EXPECTED_PATH.read_bytes(), actual)


def test_golden_demand_preserves_the_template(client):
    built = golden.build_golden_demand(client)
    actual = golden.download_docx(client, built["demand_id"])

    report = fidelity.verify(golden.TEMPLATE_PATH.read_bytes(), actual)
    assert report.is_faithful, [i.message for i in report.blocking_issues]
    assert report.required_blocks_preserved == report.required_blocks_expected
    assert report.styles_changed == 0
    assert report.headers_changed == 0
    assert report.footers_changed == 0


def test_golden_demand_states_the_case_facts_it_should(client):
    built = golden.build_golden_demand(client)
    actual = golden.download_docx(client, built["demand_id"])

    manifest = analyzer.analyze(actual)
    text = "\n".join(block.text for block in manifest.blocks)

    assert "Patrick Donahue" in text
    assert "017204635" in text
    assert "March 4, 2024" in text
    assert "$9,980.00" in text  # 6,480 + 3,500; the pending bill is excluded
    assert "$50,000.00" in text  # the confirmed policy limit
    assert "Pending" in text  # the Harbor Pain Management bill
    assert "$0.00" not in text  # a pending bill is never rendered as zero


def test_golden_demand_can_be_approved_and_locked(client):
    built = golden.build_golden_demand(client)
    demand_id = built["demand_id"]

    issues = client.post(f"/v1/demands/{demand_id}/validate", headers=golden.ATTORNEY).json()
    blocking = [i for i in issues if i["severity"] == "BLOCKING"]
    assert blocking == [], blocking

    response = client.post(
        f"/v1/demands/{demand_id}/approve",
        json={"acknowledgement": built["reference"]},
        headers=golden.ATTORNEY,
    )
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["locked"] is True
    assert approved["template_sha256"] is not None
    assert approved["fidelity_report"]["blocking_issues"] == []


def test_the_approved_bytes_are_the_bytes_that_were_approved(client):
    built = golden.build_golden_demand(client)
    demand_id = built["demand_id"]
    client.post(
        f"/v1/demands/{demand_id}/approve",
        json={"acknowledgement": built["reference"]},
        headers=golden.ATTORNEY,
    )

    first = client.get(f"/v1/demands/{demand_id}/docx", headers=golden.ATTORNEY)
    second = client.get(f"/v1/demands/{demand_id}/docx", headers=golden.ATTORNEY)
    assert first.content == second.content
    assert first.headers["X-Content-SHA256"] == second.headers["X-Content-SHA256"]
