import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ValidationTab } from "./validation";
import { CASE_ID, demand, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const baseProps = {
  caseId: CASE_ID,
  demand,
  goToTab: () => undefined,
  focusedSection: null,
};

describe("validation tab", () => {
  it("groups issues by severity and shows the rule code and values", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<ValidationTab {...baseProps} />);

    // Severity appears as a group heading and again as a badge on the issue.
    expect(screen.getAllByText("BLOCKING").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("DATE_001")).toBeInTheDocument();
    expect(
      screen.getByText(/Demand expiration \(2026-01-29\) is not after the letter date/),
    ).toBeInTheDocument();

    // The offending values are shown side by side, not just described.
    expect(screen.getByText("Expires On")).toBeInTheDocument();
    expect(screen.getByText("2026-01-29")).toBeInTheDocument();
    expect(screen.getByText("Letter Date")).toBeInTheDocument();
  });

  it("makes the blocking count obvious at the top", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<ValidationTab {...baseProps} />);

    expect(screen.getByText("1 blocking")).toBeInTheDocument();
    expect(screen.getByText("1 warning")).toBeInTheDocument();
    expect(screen.getByText("0 info")).toBeInTheDocument();
  });

  it("presents the insured/driver difference as something to confirm, not an error", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<ValidationTab {...baseProps} />);

    expect(screen.getByText("PARTY_001")).toBeInTheDocument();
    expect(screen.getAllByText("WARNING").length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByText(/flagged for confirmation rather than treated as an error/i),
    ).toBeInTheDocument();
  });

  it("navigates to the section an issue belongs to", async () => {
    mockApi(workspaceRoutes);
    const goToTab = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(<ValidationTab {...baseProps} goToTab={goToTab} />);

    await user.click(screen.getByRole("button", { name: /review party roles/i }));
    expect(goToTab).toHaveBeenCalledWith("parties");
  });

  it("re-runs validation against the backend", async () => {
    const calls = mockApi({
      ...workspaceRoutes,
      [`POST /v1/demands/${demand.id}/validate`]: { body: [] },
    });
    const user = userEvent.setup();

    renderWithProviders(<ValidationTab {...baseProps} />);

    await user.click(screen.getByRole("button", { name: /run validation/i }));

    expect(
      calls.some((call) => call.method === "POST" && call.url.includes("/validate")),
    ).toBe(true);
  });

  it("explains why there is nothing to show before the first run", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<ValidationTab {...baseProps} demand={{ ...demand, issues: [] }} />);

    expect(screen.getByText("No issues recorded")).toBeInTheDocument();
  });
});
