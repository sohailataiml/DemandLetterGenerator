"use client";

/**
 * Demand readiness: the numbers an attorney needs before signing.
 *
 * Every figure comes from the backend. Where the backend has not produced a
 * measurement yet — a demand that has never been validated, a demand with no
 * template — the row says so rather than showing a zero that would read as
 * "checked and clean".
 */

import type { ReactNode } from "react";

import { Badge, Note, Panel, PanelHeader } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import type { ClaimReport, Demand, Fact, FidelityReport, ValidationIssue } from "@/lib/api/types";

type Tone = "ok" | "warn" | "stop" | "unknown";

export interface ReadinessRow {
  label: string;
  value: string;
  tone: Tone;
  hint?: string;
}

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-ok-700",
  warn: "text-warn-700",
  stop: "text-stop-700",
  unknown: "text-ink-faint",
};

const NOT_MEASURED = "not measured";

function countTone(count: number): Tone {
  return count === 0 ? "ok" : "stop";
}

function ratioTone(part: number, whole: number): Tone {
  if (whole === 0) return "unknown";
  return part === whole ? "ok" : "stop";
}

/** Facts, citations, arithmetic, claims, template blocks — as counted rows. */
export function buildReadiness(
  demand: Demand | null,
  facts: Fact[],
  issues: ValidationIssue[],
): ReadinessRow[] {
  const rows: ReadinessRow[] = [];

  const verified = facts.filter((fact) => fact.status === "VERIFIED");
  const reviewed = facts.filter((fact) => fact.status !== "PROPOSED");
  rows.push({
    label: "Verified facts",
    value: `${verified.length} / ${reviewed.length + facts.filter((f) => f.status === "PROPOSED").length}`,
    tone: facts.some((fact) => fact.status === "PROPOSED") ? "warn" : "ok",
    hint: facts.some((fact) => fact.status === "PROPOSED")
      ? `${facts.filter((f) => f.status === "PROPOSED").length} still awaiting review`
      : undefined,
  });

  const cited = verified.filter((fact) => fact.sources.length > 0);
  rows.push({
    label: "Citation coverage",
    value: verified.length === 0 ? NOT_MEASURED : `${percent(cited.length, verified.length)}%`,
    tone: verified.length === 0 ? "unknown" : ratioTone(cited.length, verified.length),
    hint:
      verified.length === 0
        ? "no verified facts yet"
        : `${cited.length} of ${verified.length} verified facts cite a document`,
  });

  const exactSpans = verified
    .flatMap((fact) => fact.sources)
    .filter((source) => source.match_kind === "exact" || source.match_kind === "normalized");
  const allSpans = verified.flatMap((fact) => fact.sources);
  rows.push({
    label: "Exact source spans",
    value: allSpans.length === 0 ? NOT_MEASURED : `${exactSpans.length} / ${allSpans.length}`,
    tone: allSpans.length === 0 ? "unknown" : exactSpans.length === allSpans.length ? "ok" : "warn",
    hint:
      allSpans.length > exactSpans.length
        ? "some citations highlight an approximate passage"
        : undefined,
  });

  const moneyIssues = issues.filter((issue) => issue.code.startsWith("MONEY_"));
  rows.push({
    label: "Arithmetic checks",
    value: moneyIssues.length === 0 ? "all passing" : `${moneyIssues.length} failing`,
    tone: countTone(moneyIssues.length),
    hint: "totals are computed by the server, never by the model",
  });

  const claims: ClaimReport | null = demand?.claim_report ?? null;
  rows.push({
    label: "Unsupported claims",
    value: claims ? String(claims.unsupported) : NOT_MEASURED,
    tone: claims ? countTone(claims.unsupported) : "unknown",
    hint: claims
      ? `${claims.claims_checked} claim(s) checked against verified evidence`
      : "run validation to check the drafted prose",
  });

  const fidelity: FidelityReport | null = demand?.fidelity_report ?? null;
  if (demand?.template_id) {
    rows.push({
      label: "Template blocks",
      value: fidelity
        ? `${fidelity.required_blocks.preserved} / ${fidelity.required_blocks.expected}`
        : NOT_MEASURED,
      tone: fidelity
        ? ratioTone(fidelity.required_blocks.preserved, fidelity.required_blocks.expected)
        : "unknown",
      hint: fidelity ? undefined : "run validation to bind and check the template",
    });
    const mutations = fidelity
      ? fidelity.styles_changed +
        fidelity.headers_changed +
        fidelity.footers_changed +
        fidelity.numbering_changed +
        (fidelity.page_setup_changed ? 1 : 0)
      : null;
    rows.push({
      label: "Template mutations",
      value: mutations === null ? NOT_MEASURED : String(mutations),
      tone: mutations === null ? "unknown" : countTone(mutations),
      hint: "styles, headers, footers, numbering and page setup",
    });
  } else {
    rows.push({
      label: "Template blocks",
      value: "no template bound",
      tone: "unknown",
      hint: "the letter renders through the built-in layout",
    });
  }

  const blocking = issues.filter((issue) => issue.severity === "BLOCKING");
  rows.push({
    label: "Blocking issues",
    value: String(blocking.length),
    tone: countTone(blocking.length),
    hint: blocking.length > 0 ? "approval is refused while any remain" : undefined,
  });

  return rows;
}

function percent(part: number, whole: number): number {
  if (whole === 0) return 0;
  return Math.round((part / whole) * 100);
}

export function DemandReadiness({
  demand,
  facts,
  issues,
  isLoading = false,
}: {
  demand: Demand | null;
  facts: Fact[];
  issues: ValidationIssue[];
  isLoading?: boolean;
}) {
  const rows = buildReadiness(demand, facts, issues);
  const ready = rows.every((row) => row.tone === "ok");

  return (
    <Panel>
      <PanelHeader
        title="Demand readiness"
        description="Measured from the backend. A row reads “not measured” until the check has actually run."
        actions={
          isLoading ? null : (
            <Badge tone={ready ? "success" : "warning"} strong>
              {ready ? "Ready to review" : "Not ready"}
            </Badge>
          )
        }
      />
      <dl className="divide-y divide-line-soft">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2.5"
          >
            <div className="min-w-0">
              <dt className="text-meta font-medium text-ink-body">{row.label}</dt>
              {row.hint ? <p className="mt-0.5 text-2xs text-ink-faint">{row.hint}</p> : null}
            </div>
            <dd
              className={cn("tabular shrink-0 text-body font-semibold", TONE_CLASS[row.tone])}
              data-testid={`readiness-${row.label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

// ------------------------------------------------------------------- pipeline

const PIPELINE_STAGES = [
  "SOURCE",
  "EXTRACTED",
  "VERIFIED",
  "DRAFTED",
  "VALIDATED",
  "RENDERED",
  "APPROVED",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

/** How far this case has actually got, derived from backend state only. */
export function pipelineProgress(
  demand: Demand | null,
  facts: Fact[],
  documentCount: number,
  hasArtifact: boolean,
): PipelineStage[] {
  const reached: PipelineStage[] = [];
  if (documentCount > 0) reached.push("SOURCE");
  if (facts.length > 0) reached.push("EXTRACTED");
  if (facts.some((fact) => fact.status === "VERIFIED")) reached.push("VERIFIED");
  if (demand && demand.sections.length > 0) reached.push("DRAFTED");
  if (demand?.generated_at && demand.issues.length >= 0 && demand.claim_report) {
    reached.push("VALIDATED");
  }
  if (hasArtifact) reached.push("RENDERED");
  if (demand?.locked) reached.push("APPROVED");
  return reached;
}

export function PipelineStrip({
  demand,
  facts,
  documentCount,
}: {
  demand: Demand | null;
  facts: Fact[];
  documentCount: number;
}) {
  const reached = new Set(
    pipelineProgress(demand, facts, documentCount, Boolean(demand?.docx_sha256)),
  );

  return (
    <Panel>
      <PanelHeader title="Pipeline" dense />
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-2 px-4 py-3">
        {PIPELINE_STAGES.map((stage, index) => {
          const done = reached.has(stage);
          return (
            <li key={stage} className="flex items-center gap-1.5">
              <span
                data-testid={`pipeline-${stage.toLowerCase()}`}
                data-reached={done ? "true" : "false"}
                className={cn(
                  "rounded px-2 py-0.5 text-2xs font-semibold uppercase tracking-[0.07em] ring-1 ring-inset",
                  done
                    ? "bg-ok-50 text-ok-700 ring-ok-200"
                    : "bg-surface-muted text-ink-faint ring-line",
                )}
              >
                {stage}
              </span>
              {index < PIPELINE_STAGES.length - 1 ? (
                <span aria-hidden className="text-2xs text-ink-faint">
                  →
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

// ----------------------------------------------------------- blocked approval

export function BlockedApprovalPanel({
  issues,
  onNavigate,
}: {
  issues: ValidationIssue[];
  onNavigate?: (issue: ValidationIssue) => void;
}): ReactNode {
  const blocking = issues.filter((issue) => issue.severity === "BLOCKING");
  if (blocking.length === 0) return null;

  return (
    <Panel className="border-stop-200">
      <PanelHeader
        title={<span className="text-stop-800">Cannot approve</span>}
        description={`${blocking.length} blocking issue${blocking.length === 1 ? "" : "s"} must be resolved. Approval is decided by the server; this list is what it returned.`}
      />
      <ul className="divide-y divide-line-soft">
        {blocking.map((issue, index) => (
          <li key={`${issue.code}-${index}`} className="px-4 py-2.5">
            <div className="flex flex-wrap items-baseline gap-2">
              <Badge tone="danger" strong>
                {issue.code}
              </Badge>
              {issue.section_key ? (
                <span className="text-2xs text-ink-faint">{issue.section_key}</span>
              ) : null}
            </div>
            <p className="mt-1 text-meta leading-6 text-ink-body">{issue.message}</p>
            {onNavigate && issue.section_key ? (
              <button
                type="button"
                onClick={() => onNavigate(issue)}
                className="mt-1 rounded text-meta font-medium text-accent-700 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
              >
                Go to {issue.section_key}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="border-t border-line-soft px-4 py-2.5">
        <Note>
          Nothing here can be dismissed from this screen. Fix the underlying data or text and
          re-validate.
        </Note>
      </div>
    </Panel>
  );
}
