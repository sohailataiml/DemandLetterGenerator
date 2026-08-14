/**
 * Generation is a server decision. These cover the one thing the UI is allowed
 * to do about a missing template: say so, and offer the route to fixing it.
 */

import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemandTab } from "./demand";
import {
  CASE_ID,
  caseRecord,
  demand,
  documentDetail,
  facts,
  letterTemplate,
} from "@/test/fixtures";
import { mockApi, renderWithProviders, type RouteTable } from "@/test/utils";

function routes(overrides: RouteTable = {}): RouteTable {
  return {
    [`/v1/cases/${CASE_ID}`]: { body: caseRecord },
    [`/v1/cases/${CASE_ID}/demands`]: { body: [] },
    [`/v1/cases/${CASE_ID}/facts`]: { body: facts },
    [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
    [`/v1/cases/${CASE_ID}/templates`]: { body: [] },
    ...overrides,
  };
}

function renderTab(goToTab = vi.fn()) {
  renderWithProviders(
    <DemandTab caseId={CASE_ID} demand={undefined} goToTab={goToTab} focusedSection={null} />,
  );
  return goToTab;
}

describe("demand generation without a template", () => {
  it("asks for the template first and routes to Documents", async () => {
    const user = userEvent.setup();
    mockApi(routes());
    const goToTab = renderTab();

    expect(await screen.findByText("Demand template required")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Upload template" }));
    expect(goToTab).toHaveBeenCalledWith("documents");
  });

  it("does not invent a client-side block the server does not enforce", async () => {
    const user = userEvent.setup();
    const calls = mockApi(
      routes({
        [`POST /v1/cases/${CASE_ID}/demands`]: { status: 201, body: demand },
        [`POST /v1/demands/${demand.id}/generate`]: { body: demand },
      }),
    );
    renderTab();

    await screen.findByText("Demand template required");
    // Stated plainly rather than hidden: the built-in layout is what you get.
    expect(screen.getByText(/produces a letter in the built-in layout/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate without a template" }));

    const posted = calls.filter((call) => call.method === "POST").map((call) => call.url);
    expect(posted.some((url) => url.endsWith(`/v1/cases/${CASE_ID}/demands`))).toBe(true);
  });

  it("binds the case's template before generating when one is on file", async () => {
    const user = userEvent.setup();
    const calls = mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/templates`]: { body: [letterTemplate] },
        [`POST /v1/cases/${CASE_ID}/demands`]: { status: 201, body: demand },
        [`POST /v1/demands/${demand.id}/template`]: { body: letterTemplate },
        [`POST /v1/demands/${demand.id}/generate`]: { body: demand },
      }),
    );
    renderTab();

    expect(
      await screen.findByText(/will be written into demand-template.docx/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create and generate draft" }));

    const bind = await vi.waitFor(() => {
      const call = calls.find((entry) => entry.url.endsWith(`/v1/demands/${demand.id}/template`));
      expect(call).toBeDefined();
      return call!;
    });
    expect(bind.body).toEqual({ template_id: letterTemplate.id });
  });
});
