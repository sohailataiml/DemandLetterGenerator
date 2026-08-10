import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BillsTab } from "./bills";
import { CASE_ID, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const tabProps = {
  caseId: CASE_ID,
  demand: undefined,
  goToTab: () => undefined,
  focusedSection: null,
};

describe("bills and damages tab", () => {
  it("shows a bill with no amount as Pending and never as $0.00", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<BillsTab {...tabProps} />);

    const row = (await screen.findByText("Coastal Pain and Spinal Diagnostics")).closest("tr");
    expect(row).not.toBeNull();
    // The amount cell reads "Pending", and the status column agrees.
    expect(within(row!).getAllByText("Pending").length).toBeGreaterThan(0);
    expect(within(row!).queryByText("$0.00")).not.toBeInTheDocument();
    expect(within(row!).queryByText("$0")).not.toBeInTheDocument();
  });

  it("renders the backend's known total unchanged", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<BillsTab {...tabProps} />);

    expect(await screen.findByText("$6,480.00")).toBeInTheDocument();
    // 9,980.00 is the backend's figure; the UI never adds the rows itself.
    expect(screen.getAllByText("$9,980.00").length).toBeGreaterThan(0);
  });

  it("states plainly that pending charges are excluded from the total", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<BillsTab {...tabProps} />);

    expect(
      await screen.findByText(/Pending charges are excluded from the known total/i),
    ).toBeInTheDocument();
  });

  it("renders future care as a range and the claimed total from the backend", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<BillsTab {...tabProps} />);

    expect(await screen.findAllByText("$8,400.00 – $11,200.00")).not.toHaveLength(0);
    expect(screen.getByText("$21,500.00 – $24,300.00")).toBeInTheDocument();
  });

  it("shows an empty state when no bills exist", async () => {
    mockApi({
      ...workspaceRoutes,
      [`/v1/cases/${CASE_ID}/bills`]: { body: [] },
    });

    renderWithProviders(<BillsTab {...tabProps} />);

    expect(await screen.findByText("No bills recorded")).toBeInTheDocument();
  });
});
