import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PartiesTab } from "./parties";
import { CASE_ID, parties, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const tabProps = {
  caseId: CASE_ID,
  demand: undefined,
  goToTab: () => undefined,
  focusedSection: null,
};

describe("parties tab", () => {
  it("shows insured and driver as distinct roles on distinct people", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<PartiesTab {...tabProps} />);

    // Both names appear in the party list and again in the difference callout.
    expect((await screen.findAllByText("Carol Bush")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Larry L. Lawhorn").length).toBeGreaterThan(0);

    // Both role badges exist, and neither name is reconciled into the other.
    expect(screen.getAllByText("Insured").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Driver").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Named insured and driver are different people/i),
    ).toBeInTheDocument();
  });

  it("renders every role a single person holds", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<PartiesTab {...tabProps} />);

    await screen.findAllByText("Carol Bush");
    // Carol Bush is both the insured and the vehicle owner.
    expect(screen.getByText("Vehicle Owner")).toBeInTheDocument();
  });

  it("shows the recorded relationship rather than inferring one", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<PartiesTab {...tabProps} />);

    expect(await screen.findByText(/Permissive user\./)).toBeInTheDocument();
  });

  it("does not claim a mismatch when one person holds both roles", async () => {
    const single = [
      {
        ...parties[1],
        role_assignments: [
          { role: "insured" as const, relationship_note: null },
          { role: "driver" as const, relationship_note: null },
        ],
      },
    ];
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/parties`]: { body: single } });

    renderWithProviders(<PartiesTab {...tabProps} />);

    await screen.findAllByText("Carol Bush");
    expect(
      screen.queryByText(/Named insured and driver are different people/i),
    ).not.toBeInTheDocument();
  });

  it("shows an empty state when no parties are recorded", async () => {
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/parties`]: { body: [] } });

    renderWithProviders(<PartiesTab {...tabProps} />);

    expect(await screen.findByText("No parties recorded")).toBeInTheDocument();
  });
});
