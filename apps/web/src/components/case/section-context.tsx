"use client";

import { useFacts } from "@/lib/api/hooks";
import { humanize } from "@/lib/format";
import {
  Badge,
  Button,
  FactStatusBadge,
  Note,
  SectionHeading,
  Skeleton,
} from "@/components/ui/primitives";
import { useEvidence } from "./evidence";
import { IssueCard } from "./validation-list";
import type { Demand } from "@/lib/api/types";

/**
 * Right-rail context for the section under review: what validation says about
 * it, which verified facts it drew on, and one click to the source page.
 */
export function SectionContextRail({
  caseId,
  demand,
  sectionKey,
  onOpenValidation,
}: {
  caseId: string;
  demand: Demand;
  sectionKey: string;
  onOpenValidation: () => void;
}) {
  const facts = useFacts(caseId);
  const { show } = useEvidence();

  const section = demand.sections.find((item) => item.key === sectionKey);
  if (!section) return null;

  const issues = demand.issues.filter((issue) => issue.section_key === sectionKey);
  const usedFacts = (facts.data ?? []).filter((fact) => section.used_fact_ids.includes(fact.id));

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-4 py-2.5">
        <p className="eyebrow">Section context</p>
        <h2 className="mt-0.5 card-title">{section.title}</h2>
        {/* The chain this panel exists to make visible. */}
        <p className="mt-1 text-2xs text-ink-faint">
          Generated paragraph <span aria-hidden>→</span> verified facts{" "}
          <span aria-hidden>→</span> source evidence
        </p>
      </div>

      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={section.source === "ai" ? "accent" : section.source === "human" ? "warning" : "muted"}>
            {section.source === "ai"
              ? "Generated draft"
              : section.source === "human"
                ? "Attorney edited"
                : "Deterministic"}
          </Badge>
          {section.edited_by ? <Badge tone="muted">by {section.edited_by}</Badge> : null}
        </div>

        <div>
          <SectionHeading>Validation</SectionHeading>
          {issues.length === 0 ? (
            <Note>No issues recorded against this section on the last run.</Note>
          ) : (
            <div className="mt-1.5 space-y-2">
              {issues.map((issue, index) => (
                <IssueCard key={`${issue.code}-${index}`} issue={issue} compact />
              ))}
              <Button size="sm" variant="ghost" onClick={onOpenValidation}>
                Open validation
              </Button>
            </div>
          )}
        </div>

        <div>
          <SectionHeading>Facts used</SectionHeading>
          {section.source === "template" ? (
            <Note>
              This section is rendered from structured case data by the template — no model
              drafting is involved, so there are no fact citations to review.
            </Note>
          ) : facts.isLoading ? (
            <Skeleton className="mt-2 h-12 w-full" />
          ) : usedFacts.length === 0 ? (
            <Note>
              No verified facts are cited. Medical sections cannot be approved in this state.
            </Note>
          ) : (
            <ul className="mt-1.5 space-y-2">
              {usedFacts.map((fact) => (
                <li key={fact.id} className="rounded border border-line p-2">
                  <div className="flex items-center gap-1.5">
                    <FactStatusBadge status={fact.status} />
                    <Badge tone="muted">{humanize(fact.fact_type)}</Badge>
                  </div>
                  <p className="mt-1 text-meta leading-5 text-ink-body">{fact.summary}</p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="mt-1 px-1"
                    onClick={() => show({ kind: "fact", factId: fact.id })}
                  >
                    View source ({fact.sources.length})
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
