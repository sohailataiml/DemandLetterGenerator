"""Expensive work runs off the request path, and reports its progress."""

from __future__ import annotations

import json
import time

import pytest

import golden
from app.jobs import pipeline
from conftest import ATTORNEY, READONLY, upload_text_document

DOCX_MIME = golden.DOCX_MIME

#: The assignment's ceiling for a non-streaming API call.
MAX_ENQUEUE_SECONDS = 5.0


@pytest.fixture
def case_with_materials(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    for path in sorted(golden.MATERIALS_DIR.glob("*.txt")):
        upload_text_document(client, case_id, path.name, path.read_text(encoding="utf-8"))
    return seeded_case_with_facts


def _sse_events(client, job_id: str) -> list[tuple[str, dict]]:
    """Read the SSE stream to completion and parse it."""
    events: list[tuple[str, dict]] = []
    with client.stream("GET", f"/v1/jobs/{job_id}/events", headers=ATTORNEY) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in response.iter_lines():
            if line.startswith(":"):
                continue  # keep-alive comment
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                events.append((name or "message", json.loads(line[len("data: ") :])))
                if name == "done":
                    break
    return events


# --------------------------------------------------------------------------- enqueue


def test_generation_returns_202_with_a_job_id(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    response = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"].startswith("job_")
    assert body["kind"] == "generate"
    assert body["demand_id"]


def test_enqueueing_returns_well_inside_the_latency_budget(client, seeded_case_with_facts):
    """The synchronous part of the call is creating a row, not doing the work."""
    from app.jobs import runner

    case_id = seeded_case_with_facts["case_id"]
    # Measure the real asynchronous path, not the inline test runner.
    runner.set_runner(runner.ThreadJobRunner())
    try:
        started = time.monotonic()
        response = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY)
        elapsed = time.monotonic() - started
        assert response.status_code == 202
        assert elapsed < MAX_ENQUEUE_SECONDS, f"enqueue took {elapsed:.2f}s"
        assert runner.get_runner().wait(response.json()["id"], timeout=120)
    finally:
        runner.set_runner(None)


def test_a_job_creates_and_drafts_a_demand(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    assert job["status"] == "COMPLETED", job.get("error")
    demand = client.get(f"/v1/demands/{job['demand_id']}", headers=ATTORNEY).json()
    assert demand["sections"]
    assert demand["generated_at"] is not None


def test_a_job_can_target_an_existing_demand(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    job = client.post(
        f"/v1/cases/{case_id}/generate", json={"demand_id": demand["id"]}, headers=ATTORNEY
    ).json()
    assert job["demand_id"] == demand["id"]
    assert job["status"] == "COMPLETED"


def test_a_job_cannot_target_a_locked_demand(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    response = client.post(
        f"/v1/cases/{case_id}/generate", json={"demand_id": demand["id"]}, headers=ATTORNEY
    )
    assert response.status_code == 409


def test_a_reader_cannot_start_a_job(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    assert (
        client.post(f"/v1/cases/{case_id}/generate", json={}, headers=READONLY).status_code == 403
    )


# --------------------------------------------------------------------------- stages


def test_the_job_records_every_pipeline_stage(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    stages = {stage["stage"] for stage in job["stages"]}
    assert {
        pipeline.RESOLVE,
        pipeline.DRAFT,
        pipeline.CLAIMS,
        pipeline.FINANCIAL,
        pipeline.ARTIFACT,
    } <= stages


def test_a_stage_that_does_not_apply_is_skipped_not_faked(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    by_stage = {s["stage"]: s for s in job["stages"] if s["status"] != "running"}
    assert by_stage[pipeline.BIND]["status"] == "skipped"
    assert "no template" in by_stage[pipeline.BIND]["detail"]


def test_the_result_reports_what_validation_found(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    validation = job["result"]["validation"]
    assert validation["blocking"] == 0
    assert isinstance(validation["codes"], list)
    assert job["result"]["artifact"]["sha256"]


def test_extraction_runs_as_its_own_stage_when_requested(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    job = client.post(
        f"/v1/cases/{case_id}/generate", json={"extract": True}, headers=ATTORNEY
    ).json()

    assert job["result"]["extraction"]["proposed"] > 0
    extracting = [s for s in job["stages"] if s["stage"] == pipeline.EXTRACT]
    assert {s["status"] for s in extracting} == {"running", "completed"}


def test_extraction_only_jobs_propose_facts_and_verify_nothing(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    job = client.post(
        f"/v1/cases/{case_id}/extract-async", json={}, headers=ATTORNEY
    ).json()

    assert job["kind"] == "extract"
    assert job["status"] == "COMPLETED"
    assert job["result"]["proposed"] > 0

    facts = client.get(
        f"/v1/cases/{case_id}/facts?status=PROPOSED", headers=ATTORNEY
    ).json()
    assert facts


def test_a_template_bound_job_runs_the_fidelity_stage(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    template = client.post(
        f"/v1/cases/{case_id}/templates",
        files={"file": ("template.docx", golden.TEMPLATE_PATH.read_bytes(), DOCX_MIME)},
        data={"name": "Firm standard"},
        headers=ATTORNEY,
    ).json()

    job = client.post(
        f"/v1/cases/{case_id}/generate",
        json={"template_id": template["id"]},
        headers=ATTORNEY,
    ).json()

    assert job["status"] == "COMPLETED", job.get("error")
    by_stage = {s["stage"]: s for s in job["stages"] if s["status"] in ("completed", "skipped")}
    assert by_stage[pipeline.BIND]["status"] == "completed"
    assert by_stage[pipeline.FIDELITY]["status"] == "completed"
    assert job["result"]["fidelity"]["blocking_issues"] == []


def test_a_failing_job_records_the_failure_rather_than_crashing(
    client, seeded_case_with_facts, monkeypatch
):
    """A job that blows up becomes a FAILED row, not a 500 and a lost request."""
    from app.jobs import pipeline as job_pipeline

    def _explode(*args, **kwargs):
        raise RuntimeError("the drafting provider went away")

    monkeypatch.setattr(job_pipeline, "run_generation", _explode)

    case_id = seeded_case_with_facts["case_id"]
    response = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY)
    assert response.status_code == 202

    detail = client.get(f"/v1/jobs/{response.json()['id']}", headers=ATTORNEY).json()
    assert detail["status"] == "FAILED"
    assert "the drafting provider went away" in detail["error"]


# ------------------------------------------------------------------------------ SSE


def test_the_event_stream_replays_stages_and_terminates(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    events = _sse_events(client, job["id"])
    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "stage" in names

    stages = [payload["stage"] for name, payload in events if name == "stage"]
    assert pipeline.DRAFT in stages
    assert events[-1][1]["status"] == "COMPLETED"


def test_each_streamed_stage_carries_a_status_and_a_timestamp(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    job = client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY).json()

    for name, payload in _sse_events(client, job["id"]):
        if name != "stage":
            continue
        assert payload["status"] in ("running", "completed", "skipped", "failed")
        assert payload["at"]


def test_streaming_an_unknown_job_is_a_404(client):
    response = client.get("/v1/jobs/job_nope/events", headers=ATTORNEY)
    assert response.status_code == 404


def test_jobs_are_listed_for_the_case(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    client.post(f"/v1/cases/{case_id}/generate", json={}, headers=ATTORNEY)
    client.post(f"/v1/cases/{case_id}/extract-async", json={}, headers=ATTORNEY)

    jobs = client.get(f"/v1/cases/{case_id}/jobs", headers=ATTORNEY).json()
    assert {job["kind"] for job in jobs} == {"generate", "extract"}
