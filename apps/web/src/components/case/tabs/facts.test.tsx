import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FactsTab } from "./facts";
import { CASE_ID, facts, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

const tabProps = {
  caseId: CASE_ID,
  demand: undefined,
  goToTab: () => undefined,
  focusedSection: null,
};

function rowFor(summary: string) {
  return screen.getByText(summary).closest("li") as HTMLElement;
}

describe("facts tab", () => {
  it("shows lifecycle state for each fact", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<FactsTab {...tabProps} />);

    await screen.findByText(facts[0].summary);
    expect(within(rowFor(facts[0].summary)).getByText("VERIFIED")).toBeInTheDocument();
    expect(within(rowFor(facts[1].summary)).getByText("PROPOSED")).toBeInTheDocument();
  });

  it("offers verify and reject only on a proposed fact", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<FactsTab {...tabProps} />);

    await screen.findByText(facts[1].summary);
    const proposed = within(rowFor(facts[1].summary));
    expect(proposed.getByRole("button", { name: "Verify" })).toBeInTheDocument();
    expect(proposed.getByRole("button", { name: "Reject" })).toBeInTheDocument();

    const verified = within(rowFor(facts[0].summary));
    expect(verified.queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
  });

  it("does not allow a verified fact to be edited in place — only superseded", async () => {
    mockApi(workspaceRoutes);

    renderWithProviders(<FactsTab {...tabProps} />);

    await screen.findByText(facts[0].summary);
    const verified = within(rowFor(facts[0].summary));

    expect(verified.queryByRole("textbox")).not.toBeInTheDocument();
    expect(verified.getByRole("button", { name: /supersede/i })).toBeInTheDocument();
    expect(
      verified.getByText(/Verified facts are immutable — a correction creates a new revision/i),
    ).toBeInTheDocument();
  });

  it("sends the correction through the supersession endpoint, leaving the original alone", async () => {
    const calls = mockApi({
      ...workspaceRoutes,
      "POST /v1/facts/fact_verified/supersede": {
        status: 201,
        body: { ...facts[0], id: "fact_v2", revision: 2, status: "PROPOSED" },
      },
    });
    const user = userEvent.setup();

    renderWithProviders(<FactsTab {...tabProps} />);

    await screen.findByText(facts[0].summary);
    await user.click(within(rowFor(facts[0].summary)).getByRole("button", { name: /supersede/i }));

    const dialog = within(screen.getByRole("dialog"));
    await user.type(
      dialog.getByLabelText(/Reason for the correction/i),
      "Radiologist addendum",
    );
    await user.click(dialog.getByRole("button", { name: /propose revision/i }));

    const supersede = calls.find((call) => call.url.includes("/supersede"));
    expect(supersede?.method).toBe("POST");
    expect(supersede?.body).toMatchObject({ reason: "Radiologist addendum" });
    // Nothing was PATCHed or PUT against the original fact.
    expect(calls.some((call) => call.method === "PATCH" || call.method === "PUT")).toBe(false);
  });

  it("blocks verification of a fact with no source citation", async () => {
    const uncited = [{ ...facts[1], id: "fact_uncited", sources: [] }];
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/facts`]: { body: uncited } });

    renderWithProviders(<FactsTab {...tabProps} />);

    await screen.findByText(uncited[0].summary);
    expect(screen.getByRole("button", { name: "Verify" })).toBeDisabled();
    expect(screen.getByText(/Needs a source citation/i)).toBeInTheDocument();
  });

  it("shows an empty state when no facts exist", async () => {
    mockApi({ ...workspaceRoutes, [`/v1/cases/${CASE_ID}/facts`]: { body: [] } });

    renderWithProviders(<FactsTab {...tabProps} />);

    expect(await screen.findByText("No facts yet")).toBeInTheDocument();
  });
});
