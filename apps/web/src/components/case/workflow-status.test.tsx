import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkflowStatus, buildStages } from "./workflow-status";
import { demand } from "@/test/fixtures";
import { renderWithProviders } from "@/test/utils";

describe("workflow status", () => {
  it("reflects a validated draft that is blocked from approval", () => {
    renderWithProviders(
      <WorkflowStatus verifiedFactCount={5} demand={demand} validated />,
    );

    expect(screen.getByText("5 verified facts")).toBeInTheDocument();
    expect(screen.getByText("Generated")).toBeInTheDocument();
    expect(screen.getByText("1 blocking")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });

  it("shows an approved case as complete through every stage", () => {
    const approved = {
      ...demand,
      locked: true,
      status: "approved" as const,
      issues: [],
    };

    renderWithProviders(<WorkflowStatus verifiedFactCount={5} demand={approved} validated />);

    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText(`Approved · v${approved.version}`)).toBeInTheDocument();
  });

  it("does not claim validation ran when it has not", () => {
    const stages = buildStages({
      verifiedFactCount: 0,
      demand: undefined,
      validated: false,
    });

    expect(stages.map((stage) => stage.detail)).toEqual([
      "0 verified facts",
      "Not created",
      "Not run",
      "Not approved",
    ]);
    expect(stages.every((stage) => stage.state === "pending")).toBe(true);
  });

  it("labels the workflow for assistive technology", () => {
    renderWithProviders(<WorkflowStatus verifiedFactCount={1} demand={demand} validated />);
    expect(screen.getByRole("region", { name: /case workflow/i })).toBeInTheDocument();
  });
});
