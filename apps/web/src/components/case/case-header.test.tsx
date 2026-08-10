import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CaseHeader } from "./case-header";
import { CASE_ID, caseRecord, demand, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const claim = {
  id: "clm_1",
  claim_number: "884120993",
  date_of_loss: "2025-04-12",
  policy_number: "NL-1",
  policy_limit: "50000.00",
  policy_limit_confirmed: true,
  carrier: {
    id: "carr_1",
    name: "Northline Mutual",
    adjuster_name: "J. Okonkwo",
    adjuster_email: null,
    adjuster_phone: null,
    address: null,
  },
};

const settlement = {
  id: "stl_1",
  demand_type: "policy_limits",
  demand_amount: null,
  demand_is_policy_limits: true,
  expires_at: "2026-09-09T18:20:00",
  delivery_method: "email",
  conditions: [],
};

function renderHeader(overrides: Partial<Parameters<typeof CaseHeader>[0]> = {}) {
  return renderWithProviders(
    <CaseHeader
      caseId={CASE_ID}
      caseRecord={caseRecord}
      claim={claim}
      settlement={settlement}
      demand={demand}
      loading={false}
      validated
      onValidationClick={() => undefined}
      onOpenDemand={() => undefined}
      {...overrides}
    />,
  );
}

describe("case header", () => {
  it("leads with client identity, then claim and carrier context", async () => {
    mockApi(workspaceRoutes);
    renderHeader();

    expect(screen.getByRole("heading", { name: "Rosa Delgado" })).toBeInTheDocument();
    expect(screen.getByText("884120993")).toBeInTheDocument();
    expect(screen.getByText("Northline Mutual")).toBeInTheDocument();
    expect(screen.getByText("J. Okonkwo")).toBeInTheDocument();
  });

  it("summarizes the numbers that matter from backend values only", async () => {
    mockApi(workspaceRoutes);
    renderHeader();

    expect(screen.getByText("Claimed damages")).toBeInTheDocument();
    // Straight from /damages, formatted but never recomputed.
    expect(await screen.findByText("$21,500.00 – $24,300.00")).toBeInTheDocument();
    expect(screen.getByText("$50,000.00")).toBeInTheDocument();
    expect(screen.getByText("Demand expires")).toBeInTheDocument();
    // Rendered in the viewer's zone, so assert the date rather than the hour.
    expect(screen.getByText(/Sep \d+, 2026 at \d+:\d{2} (AM|PM)/)).toBeInTheDocument();
    // One VERIFIED fact in the fixture set.
    await waitFor(() => expect(screen.getByText("Verified facts")).toBeInTheDocument());
  });

  it("states a blocked draft as needing review, with the count", () => {
    mockApi(workspaceRoutes);
    renderHeader();

    expect(screen.getByText(/needs review · 1 blocking/i)).toBeInTheDocument();
  });

  it("shows an approved badge and final document actions once locked", async () => {
    mockApi(workspaceRoutes);
    const onOpenDemand = vi.fn();
    const approved = { ...demand, locked: true, status: "approved" as const, issues: [] };

    renderHeader({ demand: approved, onOpenDemand });

    expect(screen.getByText(`Approved · v${approved.version}`)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /view final demand/i }));
    expect(onOpenDemand).toHaveBeenCalled();

    expect(screen.getByRole("button", { name: /download docx/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download pdf/i })).toBeInTheDocument();
  });

  it("does not offer final document actions on a draft", () => {
    mockApi(workspaceRoutes);
    renderHeader();

    expect(screen.queryByRole("button", { name: /view final demand/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download docx/i })).not.toBeInTheDocument();
  });

  it("reports an unavailable PDF converter instead of producing a file", async () => {
    mockApi({
      ...workspaceRoutes,
      [`/v1/demands/${demand.id}/pdf`]: {
        status: 503,
        body: { detail: "PDF generation requires LibreOffice ('soffice') on PATH." },
      },
    });
    const approved = { ...demand, locked: true, status: "approved" as const, issues: [] };
    const user = userEvent.setup();

    renderHeader({ demand: approved });

    await user.click(screen.getByRole("button", { name: /download pdf/i }));

    expect(
      await screen.findByText(
        /PDF conversion is unavailable in this development environment\. DOCX remains available\./i,
      ),
    ).toBeInTheDocument();
  });

  it("says plainly when validation has not run", () => {
    mockApi(workspaceRoutes);
    renderHeader({ validated: false });

    expect(screen.getByText("Not run")).toBeInTheDocument();
  });
});
