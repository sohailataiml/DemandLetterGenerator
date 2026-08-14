import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExtractionPanel } from "./extraction";
import { CASE_ID, documentDetail, facts } from "@/test/fixtures";
import { mockApi, renderWithProviders, type RouteTable } from "@/test/utils";

const JOB_ID = "job_1";

function job(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: JOB_ID,
    case_id: CASE_ID,
    demand_id: null,
    kind: "extract",
    status,
    stages: [],
    result: null,
    error: null,
    requested_by: "attorney_1",
    created_at: "2026-02-01T10:00:00",
    started_at: null,
    finished_at: null,
    ...extra,
  };
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function routes(overrides: RouteTable = {}): RouteTable {
  return {
    [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
    [`/v1/cases/${CASE_ID}/facts`]: { body: [] },
    ...overrides,
  };
}

function renderPanel(goToTab = vi.fn()) {
  renderWithProviders(<ExtractionPanel caseId={CASE_ID} goToTab={goToTab} />);
  return goToTab;
}

describe("extraction panel", () => {
  it("waits for evidence before offering to extract anything", async () => {
    mockApi(routes({ [`/v1/cases/${CASE_ID}/documents`]: { body: [] } }));
    renderPanel();

    expect(await screen.findByText(/Upload the evidence first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Extract/ })).not.toBeInTheDocument();
  });

  it("offers extraction once a readable document is on file", async () => {
    mockApi(routes());
    renderPanel();

    expect(
      await screen.findByRole("button", { name: "Extract proposed facts" }),
    ).toBeEnabled();
  });

  it("will not extract from documents whose text could not be read", async () => {
    mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/documents`]: {
          body: [{ ...documentDetail, status: "needs_ocr" }],
        },
      }),
    );
    renderPanel();

    expect(await screen.findByText(/has to be OCR'd/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extract proposed facts" })).toBeDisabled();
  });

  it("streams the stages the backend reports and links to the proposed facts", async () => {
    const user = userEvent.setup();
    const goToTab = vi.fn();
    mockApi(
      routes({
        [`POST /v1/cases/${CASE_ID}/extract-async`]: { status: 202, body: job("QUEUED") },
        [`/v1/jobs/${JOB_ID}/events`]: {
          stream: [
            frame("stage", { stage: "extracting", status: "running", at: "2026-02-01T10:00:01" }),
            frame("stage", {
              stage: "extracting",
              status: "completed",
              detail: "14 proposed",
              at: "2026-02-01T10:00:09",
            }),
            frame("done", {
              job_id: JOB_ID,
              status: "COMPLETED",
              result: { documents: 3, proposed: 14, rejected: 2 },
            }),
          ],
        },
        [`/v1/jobs/${JOB_ID}`]: { body: job("RUNNING") },
      }),
    );
    renderPanel(goToTab);

    await user.click(await screen.findByRole("button", { name: "Extract proposed facts" }));

    // The stage label is the pipeline's own, not a fabricated checklist.
    expect(
      await screen.findByText("Reading documents and proposing facts"),
    ).toBeInTheDocument();

    const complete = await screen.findByTestId("extraction-complete");
    expect(complete).toHaveTextContent("14 proposed facts from 3 documents");

    await user.click(screen.getByRole("button", { name: "Review proposed facts" }));
    expect(goToTab).toHaveBeenCalledWith("facts");
  });

  it("reports a failed job with the server's reason and offers another attempt", async () => {
    const user = userEvent.setup();
    mockApi(
      routes({
        [`POST /v1/cases/${CASE_ID}/extract-async`]: { status: 202, body: job("QUEUED") },
        [`/v1/jobs/${JOB_ID}/events`]: {
          stream: [
            frame("stage", { stage: "extracting", status: "failed", at: "2026-02-01T10:00:03" }),
            frame("done", {
              job_id: JOB_ID,
              status: "FAILED",
              error: "ExtractionError: no readable page text",
            }),
          ],
        },
        // The polled row and the stream can settle in either order, so both
        // carry the same message — whichever wins, the attorney reads the
        // server's own reason.
        [`/v1/jobs/${JOB_ID}`]: {
          body: job("FAILED", { error: "ExtractionError: no readable page text" }),
        },
      }),
    );
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Extract proposed facts" }));

    const failure = await screen.findByTestId("extraction-failure");
    expect(failure).toHaveTextContent("no readable page text");
    expect(within(failure).getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("still reports the outcome when the event stream cannot be opened", async () => {
    const user = userEvent.setup();
    mockApi(
      routes({
        [`POST /v1/cases/${CASE_ID}/extract-async`]: { status: 202, body: job("QUEUED") },
        // No mock for the events route: the stream 404s, and the polled job row
        // is what has to carry the result through.
        [`/v1/jobs/${JOB_ID}`]: {
          body: job("COMPLETED", { result: { documents: 1, proposed: 4, rejected: 0 } }),
        },
      }),
    );
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Extract proposed facts" }));

    await waitFor(() =>
      expect(screen.getByTestId("extraction-complete")).toHaveTextContent(
        "4 proposed facts from 1 document",
      ),
    );
  });

  it("keeps proposed facts visible as outstanding work between runs", async () => {
    mockApi(routes({ [`/v1/cases/${CASE_ID}/facts`]: { body: facts } }));
    const goToTab = renderPanel();

    const proposed = facts.filter((fact) => fact.status === "PROPOSED").length;
    expect(await screen.findByText(`${proposed} awaiting review`)).toBeInTheDocument();
    expect(
      screen.getByText(/cannot be used in the letter until an attorney verifies them/),
    ).toBeInTheDocument();
    expect(goToTab).not.toHaveBeenCalled();
  });
});
