"use client";

import { useState } from "react";

import { useCaseAudit } from "@/lib/api/hooks";
import { formatDateTime, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { BadgeTone } from "@/components/ui/primitives";
import type { AuditEvent } from "@/lib/api/types";
import type { TabProps } from "../workspace";

function toneFor(event: string): BadgeTone {
  if (event.includes("APPROVED")) return "success";
  if (event.includes("REJECTED")) return "danger";
  if (event.includes("VERIFIED")) return "success";
  if (event.includes("VALIDATED")) return "accent";
  return "muted";
}

/** The one or two payload values that actually matter at a glance. */
function summarize(event: AuditEvent): string | null {
  const payload = event.payload ?? {};
  const interesting = [
    "summary",
    "reason",
    "claim_number",
    "provider_name",
    "document_type",
    "template_version",
    "blocking",
    "warnings",
    "docx_sha256",
    "key",
    "version",
  ];
  for (const key of interesting) {
    const value = payload[key];
    if (value !== undefined && value !== null && value !== "") {
      return `${humanize(key)}: ${String(value)}`;
    }
  }
  return null;
}

export function AuditTab({ caseId }: TabProps) {
  const { data, isLoading, error, refetch } = useCaseAudit(caseId);
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <Panel>
      <PanelHeader
        title="Audit trail"
        description="Append-only. This is the record that reconstructs how the final document was produced."
      />

      {isLoading ? <SkeletonRows rows={6} /> : null}
      <ErrorState
        error={error ? { message: error.message, status: error.status } : null}
        onRetry={() => refetch()}
      />
      {data && data.length === 0 ? <EmptyState title="No audit events yet" /> : null}

      {data && data.length > 0 ? (
        <ol className="divide-y divide-line-soft">
          {data.map((event) => {
            const isOpen = expanded === event.id;
            const summary = summarize(event);
            const hasPayload = Object.keys(event.payload ?? {}).length > 0;
            return (
              <li key={event.id} className="flex gap-4 px-4 py-2.5">
                <time
                  dateTime={event.created_at}
                  className="w-44 shrink-0 pt-0.5 text-2xs text-ink-faint"
                >
                  {formatDateTime(event.created_at)}
                </time>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={toneFor(event.event)}>{humanize(event.event)}</Badge>
                    <span className="text-meta text-ink-muted">
                      {event.actor}
                      {event.actor_role ? ` · ${event.actor_role}` : ""}
                    </span>
                    {event.subject_id ? (
                      <span className="font-mono text-2xs text-ink-faint">{event.subject_id}</span>
                    ) : null}
                  </div>

                  {summary && !isOpen ? (
                    <p className="mt-0.5 truncate text-meta text-ink-muted">{summary}</p>
                  ) : null}

                  {isOpen ? (
                    <pre className="mt-1.5 overflow-x-auto rounded bg-ink p-2.5 text-2xs leading-5 text-white/85">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  ) : null}

                  {hasPayload ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={isOpen}
                      className="mt-0.5 px-1"
                      onClick={() => setExpanded(isOpen ? null : event.id)}
                    >
                      {isOpen ? "Hide details" : "Details"}
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </Panel>
  );
}
