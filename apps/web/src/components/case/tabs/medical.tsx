"use client";

import { useState } from "react";

import { useFacts, useTimeline } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate, formatMoney, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LinkButton,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { BadgeTone } from "@/components/ui/primitives";
import { useEvidence } from "../evidence";
import type { TabProps } from "../workspace";

const KIND_TONE: Record<string, BadgeTone> = {
  collision: "danger",
  imaging: "accent",
  evaluation: "neutral",
  consult: "neutral",
  follow_up: "neutral",
  treatment: "neutral",
  procedure: "warning",
  diagnosis: "neutral",
};

const DOT_TONE: Record<string, string> = {
  collision: "bg-stop-600",
  imaging: "bg-accent-600",
  procedure: "bg-warn-600",
};

export function MedicalTab({ caseId }: TabProps) {
  const { data, isLoading, error, refetch } = useTimeline(caseId);
  const facts = useFacts(caseId);
  const { show } = useEvidence();
  const [expanded, setExpanded] = useState<string | null>(null);

  const medicalFacts =
    facts.data?.filter((fact) =>
      ["treatment_event", "diagnosis", "imaging_finding", "future_treatment"].includes(
        fact.fact_type,
      ),
    ) ?? [];

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Medical timeline"
          description="Built from stored treatment records, imaging, and diagnoses — not from narrative text."
        />

        {isLoading ? <SkeletonRows rows={5} /> : null}
        <ErrorState
          error={error ? { message: error.message, status: error.status } : null}
          onRetry={() => refetch()}
        />
        {data && data.length === 0 ? (
          <EmptyState
            title="No timeline entries"
            description="Add treatment events, imaging, or an accident record to build the timeline."
          />
        ) : null}

        {data && data.length > 0 ? (
          <ol className="px-4 py-3">
            {data.map((entry, index) => {
              const id = `${entry.entry_date}-${index}`;
              const isOpen = expanded === id;
              const hasDetail = Boolean(entry.detail) || entry.diagnoses.length > 0;
              const isLast = index === data.length - 1;

              return (
                <li key={id} className="flex gap-4">
                  {/* Date column */}
                  <div className="w-[6.5rem] shrink-0 pt-3 text-right">
                    <time
                      dateTime={entry.entry_date}
                      className="tabular text-meta font-semibold text-ink"
                    >
                      {formatDate(entry.entry_date)}
                    </time>
                  </div>

                  {/* Timeline indicator */}
                  <div className="relative flex w-4 shrink-0 justify-center" aria-hidden>
                    <span
                      className={cn(
                        "absolute top-[1.05rem] h-2.5 w-2.5 rounded-full ring-4 ring-white",
                        DOT_TONE[entry.kind] ?? "bg-line-strong",
                      )}
                    />
                    {!isLast ? (
                      <span className="absolute top-[1.6rem] h-[calc(100%-0.55rem)] w-px bg-line" />
                    ) : null}
                  </div>

                  {/* Content */}
                  <div className={cn("min-w-0 flex-1 pb-5 pt-2.5", isLast && "pb-2")}>
                    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                      {entry.provider ? (
                        <span className="text-body font-semibold text-ink">{entry.provider}</span>
                      ) : null}
                      <Badge tone={KIND_TONE[entry.kind] ?? "neutral"}>
                        {humanize(entry.kind)}
                      </Badge>
                      {entry.cost ? (
                        <span className="tabular text-meta text-ink-muted">
                          {formatMoney(entry.cost)}
                        </span>
                      ) : null}
                    </div>

                    <p className="mt-0.5 text-body text-ink-body">{entry.title}</p>

                    {isOpen || !hasDetail ? (
                      <>
                        {entry.detail ? (
                          <p className="mt-1.5 max-w-[70ch] text-meta leading-6 text-ink-muted">
                            {entry.detail}
                          </p>
                        ) : null}
                        {entry.diagnoses.length > 0 ? (
                          <ul className="mt-1.5 space-y-0.5">
                            {entry.diagnoses.map((diagnosis) => (
                              <li key={diagnosis} className="text-meta text-ink-muted">
                                • {diagnosis}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </>
                    ) : (
                      <p className="mt-1 truncate text-meta text-ink-faint">
                        {entry.detail ?? `${entry.diagnoses.length} recorded finding(s)`}
                      </p>
                    )}

                    <div className="mt-1.5 flex flex-wrap items-center gap-3">
                      {hasDetail ? (
                        <LinkButton
                          aria-expanded={isOpen}
                          onClick={() => setExpanded(isOpen ? null : id)}
                        >
                          {isOpen ? "Hide detail" : "Show detail"}
                        </LinkButton>
                      ) : null}
                      {entry.source_document_ids.map((documentId) => (
                        <LinkButton
                          key={documentId}
                          onClick={() => show({ kind: "document", documentId })}
                        >
                          Source document
                        </LinkButton>
                      ))}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader
          title="Medical facts"
          description="What the generated medical and imaging sections are allowed to assert."
        />
        {medicalFacts.length === 0 ? (
          <div className="px-4 py-4">
            <Note>No medical facts have been proposed yet.</Note>
          </div>
        ) : (
          <ul className="divide-y divide-line-soft">
            {medicalFacts.map((fact) => (
              <li key={fact.id} className="flex items-start justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge tone="muted">{humanize(fact.fact_type)}</Badge>
                    <span
                      className={cn(
                        "text-2xs font-semibold uppercase tracking-[0.07em]",
                        fact.status === "VERIFIED" ? "text-ok-700" : "text-warn-700",
                      )}
                    >
                      {fact.status}
                    </span>
                  </div>
                  <p className="mt-1 max-w-[80ch] text-body leading-6 text-ink-body">
                    {fact.summary}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => show({ kind: "fact", factId: fact.id })}
                >
                  Source
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
