import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DiffView, RevisionPanel } from "./revisions";
import { mockApi, renderWithProviders } from "@/test/utils";
import type { RevisionProposalDetail } from "@/lib/api/types";

const CASE_ID = "case_1";
const DEMAND_ID = "dmnd_1";

const BEFORE = "It appears that the insured driver may have failed to stop.";
const AFTER = "The insured driver failed to stop.";

function proposal(overrides: Partial<RevisionProposalDetail> = {}): RevisionProposalDetail {
  return {
    proposal: {
      id: "rev_1",
      demand_id: DEMAND_ID,
      section_key: "liability",
      instruction: "Make the liability section more forceful.",
      constraints: { preserve_amounts: true, preserve_dates: true, preserve_facts: true },
      status: "PROPOSED",
      provider_name: "stub",
      model_name: null,
      prompt_version: "revision_v1",
      validation: { valid: true, violations: [] },
      requested_by: "attorney_1",
      decided_by: null,
      decided_at: null,
      decision_note: null,
      created_at: "2026-02-01T10:00:00",
      operations: [],
    },
    before: BEFORE,
    after: AFTER,
    unified_diff:
      "--- liability (current)\n+++ liability (proposed)\n@@ -1 +1 @@\n-" +
      BEFORE +
      "\n+" +
      AFTER +
      "\n",
    violations: [],
    valid: true,
    ...overrides,
  };
}

const baseProps = {
  caseId: CASE_ID,
  demandId: DEMAND_ID,
  sectionKey: "liability",
  sectionTitle: "Liability",
  locked: false,
  canAccept: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("diff view", () => {
  it("marks added and removed lines distinctly", () => {
    renderWithProviders(<DiffView diff={"--- a\n+++ b\n-old line\n+new line\n"} />);
    const diff = screen.getByTestId("revision-diff");
    expect(diff).toHaveTextContent("-old line");
    expect(diff).toHaveTextContent("+new line");
  });

  it("says so when there is nothing to show", () => {
    renderWithProviders(<DiffView diff="" />);
    expect(screen.getByText(/identical to the current text/i)).toBeInTheDocument();
  });
});

describe("revision panel", () => {
  it("does not change the document when a revision is proposed", async () => {
    const calls = mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] },
      [`POST /v1/demands/${DEMAND_ID}/revisions`]: { status: 201, body: proposal() },
    });
    const user = userEvent.setup();
    renderWithProviders(<RevisionPanel {...baseProps} />);

    await user.type(screen.getByRole("textbox"), "Make this more forceful.");
    await user.click(screen.getByRole("button", { name: /propose revision/i }));

    expect(await screen.findByTestId("revision-diff")).toBeInTheDocument();
    expect(screen.getByText("Not applied")).toBeInTheDocument();

    // Proposing must not have written to the section.
    const mutations = calls.filter(
      (call) => call.method === "PATCH" || call.url.includes("/sections/"),
    );
    expect(mutations).toEqual([]);
  });

  it("sends the constraints the attorney selected", async () => {
    const calls = mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] },
      [`POST /v1/demands/${DEMAND_ID}/revisions`]: { status: 201, body: proposal() },
    });
    const user = userEvent.setup();
    renderWithProviders(<RevisionPanel {...baseProps} />);

    await user.type(screen.getByRole("textbox"), "Shorten this.");
    await user.click(screen.getByRole("button", { name: /propose revision/i }));

    await screen.findByTestId("revision-diff");
    const request = calls.find((call) => call.method === "POST");
    expect(request?.body).toMatchObject({
      section_key: "liability",
      instruction: "Shorten this.",
      constraints: {
        preserve_amounts: true,
        preserve_dates: true,
        preserve_facts: true,
        allow_new_facts: false,
      },
    });
  });

  it("shows the violations when a proposal breaks its constraints", async () => {
    mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] },
      [`POST /v1/demands/${DEMAND_ID}/revisions`]: {
        status: 201,
        body: proposal({
          valid: false,
          violations: [
            { code: "REVISION_002", message: "The revision changes the monetary figures." },
          ],
        }),
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<RevisionPanel {...baseProps} />);

    await user.type(screen.getByRole("textbox"), "Round the total up.");
    await user.click(screen.getByRole("button", { name: /propose revision/i }));

    expect(await screen.findByText("Violates constraints")).toBeInTheDocument();
    // The reason appears in the violations list and in the toast.
    expect(screen.getAllByText(/changes the monetary figures/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  });

  it("will not let a non-attorney accept, and says why", async () => {
    mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] },
      [`POST /v1/demands/${DEMAND_ID}/revisions`]: { status: 201, body: proposal() },
    });
    const user = userEvent.setup();
    renderWithProviders(<RevisionPanel {...baseProps} canAccept={false} />);

    await user.type(screen.getByRole("textbox"), "Make this more forceful.");
    await user.click(screen.getByRole("button", { name: /propose revision/i }));

    await screen.findByTestId("revision-diff");
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByText(/Only an attorney may apply/i)).toBeInTheDocument();
  });

  it("applies the revision only when accept is pressed", async () => {
    const calls = mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] },
      [`POST /v1/demands/${DEMAND_ID}/revisions`]: { status: 201, body: proposal() },
      "POST /v1/revisions/rev_1/accept": {
        body: proposal({ proposal: { ...proposal().proposal, status: "ACCEPTED" } }),
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<RevisionPanel {...baseProps} />);

    await user.type(screen.getByRole("textbox"), "Make this more forceful.");
    await user.click(screen.getByRole("button", { name: /propose revision/i }));
    await screen.findByTestId("revision-diff");

    expect(calls.some((call) => call.url.includes("/accept"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/accept"))).toBe(true);
    });
  });

  it("refuses to offer revisions on a locked demand", () => {
    mockApi({ [`GET /v1/demands/${DEMAND_ID}/revisions`]: { body: [] } });
    renderWithProviders(<RevisionPanel {...baseProps} locked />);

    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /propose revision/i })).toBeDisabled();
    expect(screen.getByText(/approved and locked/i)).toBeInTheDocument();
  });

  it("lists the revision history for this section", async () => {
    mockApi({
      [`GET /v1/demands/${DEMAND_ID}/revisions`]: {
        body: [
          {
            ...proposal().proposal,
            id: "rev_old",
            status: "REJECTED",
            instruction: "Soften the tone.",
            decided_by: "attorney_1",
          },
          { ...proposal().proposal, id: "rev_other", section_key: "damages" },
        ],
      },
    });
    renderWithProviders(<RevisionPanel {...baseProps} />);

    expect(await screen.findByText(/Revision history \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Soften the tone.")).toBeInTheDocument();
  });
});
