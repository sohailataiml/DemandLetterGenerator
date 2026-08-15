import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidencePanel, EvidenceProvider, useEvidence } from "./evidence";
import { CASE_ID, facts, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";
import type { RouteTable } from "@/test/utils";

/** Opens the rail on a fact, the way a click in the demand review does. */
function OpenOn({ factId }: { factId: string }) {
  const { show } = useEvidence();
  return (
    <>
      <button type="button" onClick={() => show({ kind: "fact", factId })}>
        open evidence
      </button>
      <EvidencePanel caseId={CASE_ID} />
    </>
  );
}

async function openRail(factId: string, routes: RouteTable = workspaceRoutes) {
  const calls = mockApi(routes);
  const user = userEvent.setup();
  renderWithProviders(
    <EvidenceProvider>
      <OpenOn factId={factId} />
    </EvidenceProvider>,
  );
  await user.click(screen.getByRole("button", { name: "open evidence" }));
  return { user, calls };
}

describe("source evidence rail", () => {
  it("shows the document, page and quoted passage behind a fact", async () => {
    await openRail("fact_verified");

    expect(await screen.findByText("Harbor Imaging")).toBeInTheDocument();
    expect(screen.getAllByText(/Page 2/).length).toBeGreaterThan(0);
    expect(await screen.findByTestId("quoted-evidence")).toHaveTextContent(
      "disc extrusion at L5-S1",
    );
  });

  it("offers the highlighted original for an exact citation with geometry", async () => {
    const { user } = await openRail("fact_verified");

    const open = await screen.findByRole("button", { name: /Open highlighted source/i });
    expect(screen.getByTestId("citation-status")).toHaveTextContent("Exact source match");

    await user.click(open);
    expect(await screen.findByRole("dialog", { name: /Original source/i })).toBeInTheDocument();
  });

  it("does not promise a highlight for a page-level citation", async () => {
    await openRail("fact_proposed");

    expect(await screen.findByRole("button", { name: /Open original source/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Open highlighted source/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("rail-citation-note")).toHaveTextContent(
      /No passage recorded for this citation/i,
    );
  });

  it("says a paraphrased citation is page-level only", async () => {
    const paraphrased = [
      {
        ...facts[0],
        sources: [
          {
            ...facts[0].sources[0],
            citation_status: "TEXT_ONLY" as const,
            match_kind: "approximate" as const,
            bounding_boxes: null,
          },
        ],
      },
    ];
    await openRail("fact_verified", {
      ...workspaceRoutes,
      [`/v1/cases/${CASE_ID}/facts`]: { body: paraphrased },
    });

    expect(await screen.findByTestId("rail-citation-note")).toHaveTextContent(
      /Citation available at page level only\. Exact highlight unavailable\./i,
    );
  });

  it("keeps the fact lifecycle read-only in the evidence rail", async () => {
    await openRail("fact_verified");

    await screen.findByText(facts[0].summary);
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
    // Evidence is for reading. Nothing here edits, verifies or supersedes.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    for (const label of [/^verify$/i, /^reject$/i, /supersede/i, /^edit$/i]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  it("does not fetch page geometry until the viewer is opened", async () => {
    const { user, calls } = await openRail("fact_verified");

    await screen.findByTestId("quoted-evidence");
    expect(calls.some((call) => call.url.includes("/pages/"))).toBe(false);

    await user.click(await screen.findByRole("button", { name: /Open highlighted source/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/pages/2"))).toBe(true);
    });
  });
});
