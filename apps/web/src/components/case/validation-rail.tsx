"use client";

import { Badge, Button, LinkButton, Note, SectionHeading } from "@/components/ui/primitives";
import { SafeguardsDisclosure } from "./safeguards";
import { IssueCard } from "./validation-list";
import type { Demand } from "@/lib/api/types";

/**
 * Right-rail validation health.
 *
 * A clean result collapses to a single line — an empty state has no business
 * holding a full column of a review workspace. Issues expand it back out.
 */
export function ValidationRail({
  demand,
  validated,
  onOpenValidation,
  onOpenSection,
}: {
  demand: Demand | undefined;
  validated: boolean;
  onOpenValidation: () => void;
  onOpenSection: (sectionKey: string) => void;
}) {
  const issues = demand?.issues ?? [];
  const blocking = issues.filter((issue) => issue.severity === "BLOCKING");
  const warning = issues.filter((issue) => issue.severity === "WARNING");
  const info = issues.filter((issue) => issue.severity === "INFO");
  const clean = issues.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="card-title">Validation</h2>
        {!clean ? (
          <Badge tone={blocking.length > 0 ? "danger" : "warning"}>{issues.length}</Badge>
        ) : null}
      </div>

      <div className="space-y-3 p-4">
        {!demand ? (
          <Note>No demand has been drafted for this case yet.</Note>
        ) : !validated ? (
          <div className="rounded border border-line bg-surface-muted px-3 py-2.5">
            <p className="text-meta font-medium text-ink">Validation not run</p>
            <Note>
              Approval always re-runs it, so a draft can never be approved on stale results.
            </Note>
            <Button size="sm" className="mt-2" onClick={onOpenValidation}>
              Run validation
            </Button>
          </div>
        ) : clean ? (
          /* Compact success state — one glanceable line, nothing more. */
          <div className="rounded border border-ok-200 bg-ok-50 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-meta font-semibold text-ok-700">
              <span aria-hidden>✓</span> Validation passed
            </p>
            <p className="mt-0.5 tabular text-2xs text-ok-700">0 blocking · 0 warnings</p>
            <p className="mt-1.5 text-2xs leading-4 text-ink-muted">
              Backend will revalidate before approval.
            </p>
            <LinkButton className="mt-1.5" onClick={onOpenValidation}>
              View validation details
            </LinkButton>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={blocking.length > 0 ? "danger" : "success"} strong>
                {blocking.length} blocking
              </Badge>
              <Badge tone={warning.length > 0 ? "warning" : "muted"}>
                {warning.length} warning
              </Badge>
              {info.length > 0 ? <Badge tone="muted">{info.length} info</Badge> : null}
            </div>

            {blocking.length > 0 ? (
              <div className="space-y-2">
                <SectionHeading>Must resolve before approval</SectionHeading>
                {blocking.slice(0, 3).map((issue, index) => (
                  <IssueCard
                    key={`${issue.code}-${index}`}
                    issue={issue}
                    compact
                    actions={{ onOpenSection }}
                  />
                ))}
                {blocking.length > 3 ? (
                  <LinkButton onClick={onOpenValidation}>
                    View all {blocking.length} blocking issues
                  </LinkButton>
                ) : null}
              </div>
            ) : (
              <div className="rounded border border-ok-200 bg-ok-50 px-3 py-2">
                <p className="text-meta font-medium text-ok-700">No blocking issues</p>
                <p className="mt-0.5 text-2xs leading-4 text-ink-muted">
                  An attorney can approve; the backend re-runs validation at that moment.
                </p>
              </div>
            )}

            {warning.length > 0 ? (
              <div className="space-y-2">
                <SectionHeading>To confirm</SectionHeading>
                {warning.slice(0, 2).map((issue, index) => (
                  <IssueCard
                    key={`${issue.code}-w${index}`}
                    issue={issue}
                    compact
                    actions={{ onOpenSection }}
                  />
                ))}
              </div>
            ) : null}

            <LinkButton onClick={onOpenValidation}>View validation details</LinkButton>
          </>
        )}

        <SafeguardsDisclosure />
      </div>
    </div>
  );
}
