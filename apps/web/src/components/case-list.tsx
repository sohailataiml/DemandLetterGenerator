"use client";

import Link from "next/link";

import { useCaseSummaries } from "@/lib/api/hooks";
import { formatDate, formatRelative, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { CaseSummary } from "@/lib/api/types";

function ValidationHealth({ summary }: { summary: CaseSummary }) {
  if (!summary.demand) {
    return <span className="text-meta text-ink-faint">No demand drafted</span>;
  }
  if (!summary.validation) {
    return <span className="text-meta text-ink-faint">Not yet validated</span>;
  }
  const { blocking, warning, info } = summary.validation;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge tone={blocking > 0 ? "danger" : "success"}>
        {blocking} blocking
      </Badge>
      {warning > 0 ? <Badge tone="warning">{warning} warning</Badge> : null}
      {info > 0 ? <Badge tone="neutral">{info} info</Badge> : null}
    </div>
  );
}

export function CaseList() {
  const { data, isLoading, error, refetch } = useCaseSummaries();

  return (
    <Panel>
      <PanelHeader
        title="Cases"
        description="Open a case to review its facts, evidence, and demand letter."
      />

      {isLoading ? <SkeletonRows rows={5} /> : null}
      <ErrorState
        error={error ? { message: error.message, status: error.status } : null}
        onRetry={() => refetch()}
      />

      {data && data.length === 0 ? (
        <EmptyState
          title="No cases yet"
          description={
            <>
              <p>Seed the demo case from the repository root, then reload this page:</p>
              <pre className="mt-2 rounded bg-ink px-3 py-2 text-left text-meta text-white/90">
                python scripts/demo_case.py
              </pre>
            </>
          }
          action={
            <Button variant="secondary" onClick={() => refetch()}>
              Check again
            </Button>
          }
        />
      ) : null}

      {data && data.length > 0 ? (
        <table className="w-full text-body">
          <caption className="sr-only">Cases available for review</caption>
          <thead>
            <tr className="border-b border-line text-left text-2xs uppercase tracking-[0.06em] text-ink-faint">
              <th scope="col" className="px-4 py-2 font-medium">
                Client
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Claim number
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Date of loss
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Demand
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Validation
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Last modified
              </th>
              <th scope="col" className="px-4 py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-soft">
            {data.map((summary) => (
              <tr key={summary.id} className="hover:bg-surface-muted">
                <td className="px-4 py-3">
                  <div className="font-medium text-ink">{summary.client_display_name}</div>
                  <div className="text-meta text-ink-faint">{summary.reference}</div>
                </td>
                <td className="px-4 py-3 tabular text-ink-body">
                  {summary.claim_number ?? "—"}
                </td>
                <td className="px-4 py-3 text-ink-body">{formatDate(summary.date_of_loss)}</td>
                <td className="px-4 py-3">
                  {summary.demand ? (
                    <div className="flex items-center gap-1.5">
                      <Badge tone={summary.demand.locked ? "success" : "accent"}>
                        {humanize(summary.demand.status)}
                      </Badge>
                      <span className="text-meta text-ink-faint">v{summary.demand.version}</span>
                    </div>
                  ) : (
                    <span className="text-meta text-ink-faint">—</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <ValidationHealth summary={summary} />
                </td>
                <td className="px-4 py-3 text-meta text-ink-faint">
                  {formatRelative(summary.updated_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`/cases/${summary.id}`}
                    className="inline-flex items-center rounded bg-accent-700 px-3 py-1.5 text-meta font-medium text-white hover:bg-accent-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-700"
                  >
                    Open case
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Panel>
  );
}
