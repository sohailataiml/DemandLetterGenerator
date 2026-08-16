import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DemandTab } from "./demand";
import { CASE_ID, DEMAND_ID, demand, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";
import type { RouteTable } from "@/test/utils";

const tabProps = {
  caseId: CASE_ID,
  demand,
  goToTab: () => undefined,
  focusedSection: null,
  validated: true,
  verifiedFactCount: 4,
};

/** A failure envelope shaped like the backend's AI-boundary error detail. */
function boundaryError(status: number, message: string, code: string) {
  return {
    status,
    body: { detail: { message, gateway_error_code: code, gateway_request_id: "req_x" } },
  };
}

async function generateWith(response: RouteTable[string]) {
  const calls = mockApi({
    ...workspaceRoutes,
    [`POST /v1/demands/${DEMAND_ID}/generate`]: response,
  });
  const user = userEvent.setup();
  renderWithProviders(<DemandTab {...tabProps} onValidated={() => undefined} />);
  // Each generated section offers its own "Regenerate section"; the first is
  // enough to exercise the failure path.
  const [button] = await screen.findAllByRole("button", { name: /regenerate section/i });
  await user.click(button);
  return calls;
}

describe("generation failures at the AI boundary", () => {
  it("tells the reviewer when the gateway is rate limiting, and keeps the draft", async () => {
    await generateWith(
      boundaryError(
        429,
        "The secure AI gateway is rate limiting this workspace. Wait a moment and try again; no drafting was applied.",
        "RATE_LIMIT_EXCEEDED",
      ),
    );

    expect(await screen.findByText(/rate limiting this workspace/i)).toBeInTheDocument();
    // The section on screen is the one that was already there.
    expect(screen.getByText(demand.sections[1].body.slice(0, 30), { exact: false })).toBeInTheDocument();
  });

  it("explains an oversized context instead of silently truncating", async () => {
    await generateWith(
      boundaryError(
        413,
        "Generation context is too large for the secure AI gateway. Reduce the section context or use a narrower evidence set. No demand section was modified.",
        "REQUEST_TOO_LARGE",
      ),
    );

    expect(await screen.findByText(/too large for the secure AI gateway/i)).toBeInTheDocument();
    expect(screen.getByText(/No demand section was modified/i)).toBeInTheDocument();
  });

  it("reports a privacy policy block as a decision, not a crash", async () => {
    await generateWith(
      boundaryError(
        422,
        "The secure AI gateway's privacy policy declined this content, so no drafting was applied.",
        "POLICY_VIOLATION",
      ),
    );

    expect(await screen.findByText(/privacy policy declined this content/i)).toBeInTheDocument();
  });

  it("does not erase the current section when the gateway is unavailable", async () => {
    await generateWith(
      boundaryError(
        502,
        "drafting failed at the secure AI gateway; no changes were applied.",
        "PROVIDER_UNAVAILABLE",
      ),
    );

    expect(await screen.findByText(/no changes were applied/i)).toBeInTheDocument();
    // Every section still shows the body it had before the failed attempt.
    for (const section of demand.sections.filter((item) => item.body)) {
      expect(
        screen.getByText((_, node) => node?.textContent === section.body, {
          selector: "p,pre,div",
        }),
      ).toBeInTheDocument();
    }
  });

  it("generates through this app's own API, never the gateway host", async () => {
    const calls = await generateWith({ body: demand });

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/generate"))).toBe(true);
    });
    expect(calls.every((call) => !call.url.includes("sgw-api"))).toBe(true);
  });
});
