import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseWorkspace } from "./workspace";
import { CASE_ID, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

describe("case workspace", () => {
  it("loads the case header from the backend", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<CaseWorkspace caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "Rosa Delgado" })).toBeInTheDocument();
    expect(screen.getByText("AB-2025-0001")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("884120993")).toBeInTheDocument());
    expect(screen.getByText("Northline Mutual")).toBeInTheDocument();
    expect(screen.getByText("J. Okonkwo")).toBeInTheDocument();
  });

  it("shows every workspace section in the navigation", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<CaseWorkspace caseId={CASE_ID} />);

    const nav = await screen.findByRole("navigation", { name: /case sections/i });
    for (const label of [
      "Overview",
      "Parties",
      "Liability",
      "Medical",
      "Bills",
      "Facts",
      "Documents",
      "Demand",
      "Validation",
      "Audit",
    ]) {
      expect(within(nav).getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("reports a missing case rather than rendering an empty shell", async () => {
    mockApi({
      ...workspaceRoutes,
      [`/v1/cases/${CASE_ID}`]: { status: 404, body: { detail: "case not found" } },
    });

    renderWithProviders(<CaseWorkspace caseId={CASE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("case not found");
  });
});
