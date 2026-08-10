"use client";

import { humanize } from "@/lib/format";
import { Badge, Button, Note, SeverityBadge } from "@/components/ui/primitives";
import type { Severity, ValidationIssue } from "@/lib/api/types";

const SEVERITY_ORDER: Severity[] = ["BLOCKING", "WARNING", "INFO"];

const SEVERITY_FRAME: Record<Severity, string> = {
  BLOCKING: "border-stop-200 bg-stop-50/60",
  WARNING: "border-warn-200 bg-warn-50/50",
  INFO: "border-line bg-white",
};

const SEVERITY_EXPLANATION: Record<Severity, string> = {
  BLOCKING: "Approval is refused while any of these remain.",
  WARNING: "Reviewed and acknowledged, these do not block approval.",
  INFO: "Context worth noting before release.",
};

/** Rules where the issue is something to confirm, not necessarily an error. */
const CONFIRMATION_CODES = new Set(["PARTY_001", "MONEY_003", "DATE_003"]);

export interface IssueActions {
  onOpenSection?: (sectionKey: string) => void;
  onOpenParties?: () => void;
  onEditExpiration?: () => void;
  onOpenBills?: () => void;
  onOpenFacts?: () => void;
}

function detailEntries(details: Record<string, unknown>): [string, string][] {
  return Object.entries(details).map(([key, value]) => [
    humanize(key),
    Array.isArray(value) ? value.join(", ") : String(value ?? "—"),
  ]);
}

function actionFor(issue: ValidationIssue, actions: IssueActions) {
  if (issue.code === "DATE_001" || issue.code === "DOCUMENT_001") {
    if (actions.onEditExpiration) {
      return { label: "Edit expiration", run: actions.onEditExpiration };
    }
  }
  if (issue.code.startsWith("PARTY") && actions.onOpenParties) {
    return { label: "Review party roles", run: actions.onOpenParties };
  }
  if (issue.code.startsWith("MONEY") && actions.onOpenBills) {
    return { label: "Review bills", run: actions.onOpenBills };
  }
  if (issue.code.startsWith("SOURCE") && actions.onOpenFacts) {
    return { label: "Review facts", run: actions.onOpenFacts };
  }
  if (issue.section_key && actions.onOpenSection) {
    const sectionKey = issue.section_key;
    return { label: "Open section", run: () => actions.onOpenSection?.(sectionKey) };
  }
  return null;
}

export function IssueCard({
  issue,
  actions = {},
  compact = false,
}: {
  issue: ValidationIssue;
  actions?: IssueActions;
  compact?: boolean;
}) {
  const action = actionFor(issue, actions);
  const entries = detailEntries(issue.details ?? {});

  return (
    <article className={`rounded border px-3 py-2.5 ${SEVERITY_FRAME[issue.severity]}`}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={issue.severity} />
        <span className="font-mono text-meta font-medium text-ink-body">{issue.code}</span>
        {issue.section_key ? <Badge tone="muted">{humanize(issue.section_key)}</Badge> : null}
      </div>

      <p className="mt-1.5 text-body leading-6 text-ink-body">{issue.message}</p>

      {CONFIRMATION_CODES.has(issue.code) ? (
        <Note>
          This may be legitimate. It is flagged for confirmation rather than treated as an error.
        </Note>
      ) : null}

      {!compact && entries.length > 0 ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-line/70 pt-2">
          {entries.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-2xs font-medium uppercase tracking-[0.06em] text-ink-faint">
                {label}
              </dt>
              <dd className="truncate text-meta text-ink-body" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {action ? (
        <div className="mt-2">
          <Button size="sm" variant="secondary" onClick={action.run}>
            {action.label}
          </Button>
        </div>
      ) : null}
    </article>
  );
}

export function ValidationIssueList({
  issues,
  actions,
  compact,
}: {
  issues: ValidationIssue[];
  actions?: IssueActions;
  compact?: boolean;
}) {
  return (
    <div className="space-y-5">
      {SEVERITY_ORDER.map((severity) => {
        const group = issues.filter((issue) => issue.severity === severity);
        if (group.length === 0) return null;
        return (
          <section key={severity}>
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-2xs font-semibold uppercase tracking-[0.08em] text-ink-muted">
                {severity}
              </h3>
              <span className="text-2xs text-ink-faint">
                {group.length} · {SEVERITY_EXPLANATION[severity]}
              </span>
            </div>
            <div className="space-y-2">
              {group.map((issue, index) => (
                <IssueCard
                  key={`${issue.code}-${issue.section_key ?? "case"}-${index}`}
                  issue={issue}
                  actions={actions}
                  compact={compact}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
