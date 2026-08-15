import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidencePanel, EvidenceProvider } from "./evidence";
import { SectionContextRail } from "./section-context";
import { CASE_ID, demand, facts, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

/**
 * The chain the product is built around: a generated section names the facts it
 * used, a fact names its citation, and the citation opens the original source.
 */
describe("section context → fact → citation", () => {
  const section = demand.sections.find((item) => item.used_fact_ids.length > 0)!;

  it("shows how precise the evidence behind each fact used is", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(
      <EvidenceProvider>
        <SectionContextRail
          caseId={CASE_ID}
          demand={demand}
          sectionKey={section.key}
          onOpenValidation={() => undefined}
        />
      </EvidenceProvider>,
    );

    await screen.findByText(facts[0].summary);
    expect(screen.getByTestId("citation-status")).toHaveTextContent("Exact source match");
  });

  it("opens the citation's evidence from the fact the section used", async () => {
    mockApi(workspaceRoutes);
    const user = userEvent.setup();

    renderWithProviders(
      <EvidenceProvider>
        <SectionContextRail
          caseId={CASE_ID}
          demand={demand}
          sectionKey={section.key}
          onOpenValidation={() => undefined}
        />
        <EvidencePanel caseId={CASE_ID} />
      </EvidenceProvider>,
    );

    await screen.findByText(facts[0].summary);
    await user.click(screen.getByRole("button", { name: /View source \(1\)/ }));

    expect(await screen.findByText("Source evidence")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Open highlighted source/i }),
    ).toBeInTheDocument();
  });
});
