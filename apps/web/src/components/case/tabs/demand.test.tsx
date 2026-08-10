import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DemandTab } from "./demand";
import { CASE_ID, caseRecord, demand, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const baseProps = {
  caseId: CASE_ID,
  demand,
  goToTab: () => undefined,
  focusedSection: null,
};

describe("demand tab", () => {
  it("renders the letter sections in order with their generation state", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<DemandTab {...baseProps} />);

    // Each section appears twice: once in the section index, once in the letter.
    expect(await screen.findByRole("heading", { name: "Claim Information" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Claim Information" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Diagnostic Imaging Findings" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Deterministic")).toBeInTheDocument();
    expect(screen.getByText("Generated draft")).toBeInTheDocument();
    expect(screen.getByText("1 fact")).toBeInTheDocument();
  });

  it("makes the blocking count prominent and offers a way to review it", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<DemandTab {...baseProps} />);

    expect(
      await screen.findByText(/1 blocking issue must be resolved before this demand can be approved/i),
    ).toBeInTheDocument();
  });

  it("requires the case reference before approval can be submitted", async () => {
    mockApi(workspaceRoutes);
    const user = userEvent.setup();

    renderWithProviders(<DemandTab {...baseProps} />);

    await user.click(await screen.findByRole("button", { name: /approve final demand/i }));

    const dialog = within(screen.getByRole("dialog"));
    expect(
      dialog.getByText(/You are approving the exact current demand version/i),
    ).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: /approve and lock/i })).toBeDisabled();
  });

  it("surfaces the backend's blocking issues when approval is refused", async () => {
    mockApi({
      ...workspaceRoutes,
      [`POST /v1/demands/${demand.id}/approve`]: {
        status: 409,
        body: {
          detail: {
            message: "2 blocking validation issue(s) must be resolved before approval",
            blocking_issues: [
              { code: "DATE_001", message: "Demand expiration is not after the letter date.", section_key: "demand_title" },
              { code: "NARRATIVE_002", message: "Section 'liability' was not drafted.", section_key: "liability" },
            ],
          },
        },
      },
    });
    const user = userEvent.setup();

    renderWithProviders(<DemandTab {...baseProps} />);

    await user.click(await screen.findByRole("button", { name: /approve final demand/i }));
    const dialog = within(screen.getByRole("dialog"));
    await user.type(dialog.getByLabelText(/type the case reference/i), caseRecord.reference);
    await user.click(dialog.getByRole("button", { name: /approve and lock/i }));

    expect(await screen.findByText(/The backend refused approval/i)).toBeInTheDocument();
    expect(screen.getByText("DATE_001")).toBeInTheDocument();
    expect(screen.getByText(/Section 'liability' was not drafted/)).toBeInTheDocument();
  });

  it("handles an unavailable PDF converter without pretending a PDF exists", async () => {
    mockApi({
      ...workspaceRoutes,
      [`/v1/demands/${demand.id}/pdf`]: {
        status: 503,
        body: { detail: "PDF generation requires LibreOffice ('soffice') on PATH." },
      },
    });
    const user = userEvent.setup();

    renderWithProviders(<DemandTab {...baseProps} />);

    await user.click(await screen.findByRole("button", { name: /generate pdf/i }));

    expect(
      await screen.findByText(
        /PDF conversion is unavailable in this development environment\. DOCX remains available\./i,
      ),
    ).toBeInTheDocument();
  });

  it("shows the approval record and hides editing once the demand is locked", async () => {
    const approved = {
      ...demand,
      status: "approved" as const,
      locked: true,
      approved_by: "attorney_1",
      approved_at: "2026-02-06T15:04:00",
      docx_sha256: "f".repeat(64),
      issues: [],
    };
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/demands`]: { body: [approved] } });

    renderWithProviders(<DemandTab {...baseProps} demand={approved} />);

    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(screen.getByText(/by attorney_1/)).toBeInTheDocument();
    expect(screen.getByText("f".repeat(64))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve final demand/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("offers to create a draft when the case has no demand", async () => {
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/demands`]: { body: [] } });

    renderWithProviders(<DemandTab {...baseProps} demand={undefined} />);

    expect(await screen.findByText("No demand drafted")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create and generate draft/i }),
    ).toBeInTheDocument();
  });
});
