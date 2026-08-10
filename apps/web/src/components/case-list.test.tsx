import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseList } from "./case-list";
import { caseSummary } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";

describe("case list", () => {
  it("renders a row per case with claim metadata and validation health", async () => {
    mockApi({ "/v1/case-summaries": { body: [caseSummary] } });

    renderWithProviders(<CaseList />);

    expect(await screen.findByText("Rosa Delgado")).toBeInTheDocument();
    expect(screen.getByText("884120993")).toBeInTheDocument();
    expect(screen.getByText("Apr 12, 2025")).toBeInTheDocument();
    expect(screen.getByText("1 blocking")).toBeInTheDocument();
    expect(screen.getByText("2 warning")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open case/i })).toHaveAttribute(
      "href",
      `/cases/${caseSummary.id}`,
    );
  });

  it("explains how to seed the demo case when there are none", async () => {
    mockApi({ "/v1/case-summaries": { body: [] } });

    renderWithProviders(<CaseList />);

    expect(await screen.findByText("No cases yet")).toBeInTheDocument();
    expect(screen.getByText("python scripts/demo_case.py")).toBeInTheDocument();
  });

  it("distinguishes a case with no demand from one that has never been validated", async () => {
    mockApi({
      "/v1/case-summaries": {
        body: [
          { ...caseSummary, demand: null, validation: null },
          { ...caseSummary, id: "case_2", validation: null },
        ],
      },
    });

    renderWithProviders(<CaseList />);

    expect(await screen.findByText("No demand drafted")).toBeInTheDocument();
    expect(screen.getByText("Not yet validated")).toBeInTheDocument();
  });

  it("surfaces an unreachable backend instead of an empty table", async () => {
    mockApi({});

    renderWithProviders(<CaseList />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
