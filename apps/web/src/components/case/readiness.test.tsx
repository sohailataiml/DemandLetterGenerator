import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  BlockedApprovalPanel,
  DemandReadiness,
  PipelineStrip,
  buildReadiness,
  pipelineProgress,
} from "./readiness";
import { demand as demandFixture, facts as factsFixture } from "@/test/fixtures";
import type { Demand, Fact, ValidationIssue } from "@/lib/api/types";

const verifiedFact = factsFixture.find((fact) => fact.status === "VERIFIED") as Fact;
const proposedFact = factsFixture.find((fact) => fact.status === "PROPOSED") as Fact;

function withReport(overrides: Partial<Demand>): Demand {
  return { ...demandFixture, ...overrides };
}

describe("demand readiness", () => {
  it("reports a measurement only when the backend has produced one", () => {
    const rows = buildReadiness(
      withReport({ claim_report: null, fidelity_report: null, template_id: null }),
      [verifiedFact],
      [],
    );
    const claims = rows.find((row) => row.label === "Unsupported claims");
    expect(claims?.value).toBe("not measured");
    expect(claims?.tone).toBe("unknown");
  });

  it("counts unsupported claims from the backend's claim report", () => {
    const rows = buildReadiness(
      withReport({
        claim_report: {
          claims_checked: 9,
          supported: 7,
          partially_supported: 0,
          unsupported: 2,
          sections: ["liability"],
          unsupported_claims: [],
        },
      }),
      [verifiedFact],
      [],
    );
    const claims = rows.find((row) => row.label === "Unsupported claims");
    expect(claims?.value).toBe("2");
    expect(claims?.tone).toBe("stop");
  });

  it("says a template is not bound rather than showing a clean zero", () => {
    const rows = buildReadiness(withReport({ template_id: null }), [verifiedFact], []);
    const blocks = rows.find((row) => row.label === "Template blocks");
    expect(blocks?.value).toBe("no template bound");
    expect(blocks?.tone).toBe("unknown");
  });

  it("reports template mutations when a fidelity report exists", () => {
    const rows = buildReadiness(
      withReport({
        template_id: "tpl_1",
        fidelity_report: {
          template_hash: "abc",
          required_blocks: { expected: 47, preserved: 47 },
          styles_changed: 0,
          headers_changed: 0,
          footers_changed: 0,
          numbering_changed: 0,
          page_setup_changed: false,
          blocking_issues: [],
          warnings: [],
        },
      }),
      [verifiedFact],
      [],
    );
    expect(rows.find((row) => row.label === "Template blocks")?.value).toBe("47 / 47");
    expect(rows.find((row) => row.label === "Template mutations")?.value).toBe("0");
  });

  it("counts blocking issues and marks them as stopping", () => {
    const issues: ValidationIssue[] = [
      { code: "MONEY_001", severity: "BLOCKING", message: "x", section_key: null, details: {} },
      { code: "DATE_003", severity: "WARNING", message: "y", section_key: null, details: {} },
    ];
    const rows = buildReadiness(withReport({}), [verifiedFact], issues);
    expect(rows.find((row) => row.label === "Blocking issues")?.value).toBe("1");
    expect(rows.find((row) => row.label === "Blocking issues")?.tone).toBe("stop");
    expect(rows.find((row) => row.label === "Arithmetic checks")?.value).toBe("1 failing");
  });

  it("flags facts still awaiting review", () => {
    const rows = buildReadiness(withReport({}), [verifiedFact, proposedFact], []);
    const row = rows.find((r) => r.label === "Verified facts");
    expect(row?.tone).toBe("warn");
    expect(row?.hint).toContain("awaiting review");
  });

  it("distinguishes exact spans from approximate ones", () => {
    const approximate: Fact = {
      ...verifiedFact,
      id: "fact_approx",
      sources: [{ ...verifiedFact.sources[0], id: "fsrc_x", match_kind: "approximate" }],
    };
    const rows = buildReadiness(withReport({}), [verifiedFact, approximate], []);
    const row = rows.find((r) => r.label === "Exact source spans");
    expect(row?.value).toBe("1 / 2");
    expect(row?.tone).toBe("warn");
  });

  it("renders the panel with a readiness verdict", () => {
    render(<DemandReadiness demand={withReport({})} facts={[verifiedFact]} issues={[]} />);
    expect(screen.getByText("Demand readiness")).toBeInTheDocument();
    expect(screen.getByTestId("readiness-blocking-issues")).toHaveTextContent("0");
  });
});

describe("pipeline", () => {
  it("only marks stages the backend has actually reached", () => {
    // A demand with sections but no documents, no facts and no claim report:
    // drafted, but nothing before or after it.
    const reached = pipelineProgress(withReport({ claim_report: null }), [], 0, false);
    expect(reached).toEqual(["DRAFTED"]);
    expect(reached).not.toContain("SOURCE");
    expect(reached).not.toContain("VALIDATED");
    expect(reached).not.toContain("RENDERED");
  });

  it("advances as each stage completes", () => {
    const reached = pipelineProgress(
      withReport({ locked: true, docx_sha256: "abc" }),
      [verifiedFact],
      2,
      true,
    );
    expect(reached).toContain("SOURCE");
    expect(reached).toContain("VERIFIED");
    expect(reached).toContain("DRAFTED");
    expect(reached).toContain("VALIDATED");
    expect(reached).toContain("RENDERED");
    expect(reached).toContain("APPROVED");
  });

  it("does not mark VERIFIED when every fact is still proposed", () => {
    const reached = pipelineProgress(withReport({}), [proposedFact], 1, false);
    expect(reached).toContain("EXTRACTED");
    expect(reached).not.toContain("VERIFIED");
  });

  it("renders each stage with its reached state", () => {
    render(<PipelineStrip demand={withReport({})} facts={[verifiedFact]} documentCount={1} />);
    expect(screen.getByTestId("pipeline-source")).toHaveAttribute("data-reached", "true");
    expect(screen.getByTestId("pipeline-approved")).toHaveAttribute("data-reached", "false");
  });
});

describe("blocked approval panel", () => {
  const blocking: ValidationIssue[] = [
    {
      code: "MONEY_002",
      severity: "BLOCKING",
      message: "Metro Imaging bill is still pending.",
      section_key: "medical_expense_summary",
      details: {},
    },
    {
      code: "CLAIM_001",
      severity: "BLOCKING",
      message: "Paragraph 4 contains an unsupported factual assertion.",
      section_key: "liability",
      details: {},
    },
  ];

  it("renders nothing when there is nothing blocking", () => {
    const { container } = render(<BlockedApprovalPanel issues={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every blocking issue with its code and message", () => {
    render(<BlockedApprovalPanel issues={blocking} />);
    expect(screen.getByText("Cannot approve")).toBeInTheDocument();
    expect(screen.getByText("MONEY_002")).toBeInTheDocument();
    expect(screen.getByText("Metro Imaging bill is still pending.")).toBeInTheDocument();
    expect(screen.getByText("CLAIM_001")).toBeInTheDocument();
  });

  it("ignores warnings", () => {
    render(
      <BlockedApprovalPanel
        issues={[
          { code: "DATE_003", severity: "WARNING", message: "future date", section_key: null, details: {} },
        ]}
      />,
    );
    expect(screen.queryByText("Cannot approve")).not.toBeInTheDocument();
  });

  it("offers a link to the offending section", async () => {
    const seen: string[] = [];
    render(
      <BlockedApprovalPanel issues={blocking} onNavigate={(issue) => seen.push(issue.code)} />,
    );
    screen.getByRole("button", { name: "Go to liability" }).click();
    expect(seen).toEqual(["CLAIM_001"]);
  });
});
