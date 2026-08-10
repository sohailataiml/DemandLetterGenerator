import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ValidationRail } from "./validation-rail";
import { demand } from "@/test/fixtures";
import { renderWithProviders } from "@/test/utils";

const noop = () => undefined;

describe("validation rail", () => {
  it("collapses to a single compact line when there are no issues", () => {
    renderWithProviders(
      <ValidationRail
        demand={{ ...demand, issues: [] }}
        validated
        onOpenValidation={noop}
        onOpenSection={noop}
      />,
    );

    expect(screen.getByText("Validation passed")).toBeInTheDocument();
    expect(screen.getByText("0 blocking · 0 warnings")).toBeInTheDocument();
    expect(screen.getByText("Backend will revalidate before approval.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /view validation details/i }),
    ).toBeInTheDocument();

    // No issue cards, no severity headings taking up the column.
    expect(screen.queryByText("Must resolve before approval")).not.toBeInTheDocument();
  });

  it("expands with issue cards when blocking issues exist", () => {
    renderWithProviders(
      <ValidationRail
        demand={demand}
        validated
        onOpenValidation={noop}
        onOpenSection={noop}
      />,
    );

    expect(screen.getByText("Must resolve before approval")).toBeInTheDocument();
    expect(screen.getByText("DATE_001")).toBeInTheDocument();
    expect(screen.getByText("1 blocking")).toBeInTheDocument();
    expect(screen.queryByText("Validation passed")).not.toBeInTheDocument();
  });

  it("surfaces warnings for confirmation even with nothing blocking", () => {
    const warningOnly = {
      ...demand,
      issues: demand.issues.filter((issue) => issue.severity === "WARNING"),
    };

    renderWithProviders(
      <ValidationRail
        demand={warningOnly}
        validated
        onOpenValidation={noop}
        onOpenSection={noop}
      />,
    );

    expect(screen.getByText("No blocking issues")).toBeInTheDocument();
    expect(screen.getByText("To confirm")).toBeInTheDocument();
    expect(screen.getByText("PARTY_001")).toBeInTheDocument();
  });

  it("prompts to run validation before anything has been recorded", async () => {
    const onOpenValidation = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <ValidationRail
        demand={{ ...demand, issues: [] }}
        validated={false}
        onOpenValidation={onOpenValidation}
        onOpenSection={noop}
      />,
    );

    expect(screen.getByText("Validation not run")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /run validation/i }));
    expect(onOpenValidation).toHaveBeenCalled();
  });

  it("keeps the safeguards explanation collapsed rather than permanently expanded", () => {
    renderWithProviders(
      <ValidationRail
        demand={{ ...demand, issues: [] }}
        validated
        onOpenValidation={noop}
        onOpenSection={noop}
      />,
    );

    const disclosure = screen.getByText("How safeguards work").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).not.toHaveAttribute("open");
    // The principles are still present, one disclosure click away.
    expect(
      screen.getByText(/nothing verifies itself/i),
    ).toBeInTheDocument();
  });
});
