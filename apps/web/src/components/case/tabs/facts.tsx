"use client";

import { useState } from "react";

import { useFacts, useRejectFact, useSupersedeFact, useVerifyFact } from "@/lib/api/hooks";
import { formatDate, formatDateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FactStatusBadge,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useEvidence } from "../evidence";
import type { Fact, FactStatus } from "@/lib/api/types";
import type { TabProps } from "../workspace";

const FILTERS: { key: FactStatus | "ALL"; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "PROPOSED", label: "Proposed" },
  { key: "VERIFIED", label: "Verified" },
  { key: "REJECTED", label: "Rejected" },
  { key: "SUPERSEDED", label: "Superseded" },
];

const STATUS_STRIPE: Record<string, string> = {
  VERIFIED: "border-l-ok-600",
  PROPOSED: "border-l-warn-600",
  REJECTED: "border-l-line-strong",
  SUPERSEDED: "border-l-line-strong",
};

function FactRow({
  fact,
  factsById,
  onVerify,
  onReject,
  onSupersede,
  busy,
}: {
  fact: Fact;
  factsById: Map<string, Fact>;
  onVerify: (fact: Fact) => void;
  onReject: (fact: Fact) => void;
  onSupersede: (fact: Fact) => void;
  busy: boolean;
}) {
  const { show } = useEvidence();
  const supersededBy = fact.superseded_by_id ? factsById.get(fact.superseded_by_id) : undefined;
  const supersedes = fact.supersedes_id ? factsById.get(fact.supersedes_id) : undefined;
  const isRetired = fact.status === "REJECTED" || fact.status === "SUPERSEDED";

  return (
    <li
      className={cn(
        "border-l-[3px] px-4 py-3.5",
        STATUS_STRIPE[fact.status] ?? "border-l-transparent",
        isRetired && "bg-surface-muted/60",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <FactStatusBadge status={fact.status} />
        <Badge tone="muted">{humanize(fact.fact_type)}</Badge>
        {fact.revision > 1 ? <Badge tone="neutral">revision {fact.revision}</Badge> : null}
        {fact.status === "PROPOSED" ? (
          <span className="text-2xs font-medium text-warn-700">Awaiting human review</span>
        ) : null}
        <span className="ml-auto text-2xs text-ink-faint">
          Created {formatDate(fact.created_at)}
        </span>
      </div>

      <p
        className={cn(
          "mt-2 max-w-[85ch] text-body leading-6",
          isRetired ? "text-ink-muted" : "text-ink-body",
        )}
      >
        {fact.summary}
      </p>

      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-faint">
        <div className="flex gap-1">
          <dt>Proposed by</dt>
          <dd className="font-medium text-ink-muted">{fact.proposed_by}</dd>
        </div>
        {fact.reviewed_by ? (
          <div className="flex gap-1">
            <dt>{fact.status === "REJECTED" ? "Rejected by" : "Verified by"}</dt>
            <dd className="font-medium text-ink-muted">{fact.reviewed_by}</dd>
          </div>
        ) : null}
        {fact.reviewed_at ? (
          <div className="flex gap-1">
            <dt>Reviewed</dt>
            <dd className="font-medium text-ink-muted">{formatDateTime(fact.reviewed_at)}</dd>
          </div>
        ) : null}
      </dl>

      {fact.rejection_reason ? (
        <p className="mt-2 text-meta text-stop-700">Rejected: {fact.rejection_reason}</p>
      ) : null}
      {supersededBy ? (
        <p className="mt-2 border-l-2 border-line pl-2.5 text-meta text-ink-muted">
          Superseded by revision {supersededBy.revision}: “{supersededBy.summary}”
        </p>
      ) : null}
      {supersedes ? (
        <p className="mt-2 border-l-2 border-line pl-2.5 text-meta text-ink-muted">
          Supersedes revision {supersedes.revision}: “{supersedes.summary}”
        </p>
      ) : null}

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => show({ kind: "fact", factId: fact.id })}
        >
          View source
          <span className="ml-0.5 rounded bg-surface-sunken px-1 text-2xs text-ink-muted">
            {fact.sources.length}
          </span>
        </Button>

        {fact.status === "PROPOSED" ? (
          <>
            <Button
              size="sm"
              variant="primary"
              disabled={busy || fact.sources.length === 0}
              onClick={() => onVerify(fact)}
              title={
                fact.sources.length === 0
                  ? "A fact cannot be verified without a source citation"
                  : undefined
              }
            >
              Verify
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onReject(fact)}>
              Reject
            </Button>
            {fact.sources.length === 0 ? (
              <span className="text-2xs text-warn-700">
                Needs a source citation before it can be verified.
              </span>
            ) : null}
          </>
        ) : null}

        {fact.status === "VERIFIED" && !fact.superseded_by_id ? (
          <>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onSupersede(fact)}>
              Supersede…
            </Button>
            <span className="text-2xs text-ink-faint">
              Verified facts are immutable — a correction creates a new revision.
            </span>
          </>
        ) : null}
      </div>
    </li>
  );
}

export function FactsTab({ caseId }: TabProps) {
  const { data, isLoading, error, refetch } = useFacts(caseId);
  const verify = useVerifyFact(caseId);
  const reject = useRejectFact(caseId);
  const supersede = useSupersedeFact(caseId);
  const toast = useToast();

  const [filter, setFilter] = useState<FactStatus | "ALL">("ALL");
  const [rejecting, setRejecting] = useState<Fact | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [superseding, setSuperseding] = useState<Fact | null>(null);
  const [supersedeSummary, setSupersedeSummary] = useState("");
  const [supersedeReason, setSupersedeReason] = useState("");

  const factsById = new Map((data ?? []).map((fact) => [fact.id, fact]));
  const visible = (data ?? []).filter((fact) => filter === "ALL" || fact.status === filter);
  const counts = {
    PROPOSED: (data ?? []).filter((f) => f.status === "PROPOSED").length,
    VERIFIED: (data ?? []).filter((f) => f.status === "VERIFIED").length,
  };

  const busy = verify.isPending || reject.isPending || supersede.isPending;

  const handleVerify = (fact: Fact) => {
    verify.mutate(fact.id, {
      onSuccess: () =>
        toast.push({ tone: "success", title: "Fact verified", description: fact.summary }),
      onError: (apiError) =>
        toast.push({ tone: "error", title: "Could not verify", description: apiError.message }),
    });
  };

  const submitReject = () => {
    if (!rejecting) return;
    reject.mutate(
      { factId: rejecting.id, reason: rejectReason },
      {
        onSuccess: () => {
          toast.push({ tone: "success", title: "Fact rejected" });
          setRejecting(null);
          setRejectReason("");
        },
        onError: (apiError) =>
          toast.push({ tone: "error", title: "Could not reject", description: apiError.message }),
      },
    );
  };

  const submitSupersede = () => {
    if (!superseding) return;
    supersede.mutate(
      {
        factId: superseding.id,
        fact_type: superseding.fact_type,
        value: superseding.value,
        summary: supersedeSummary,
        reason: supersedeReason,
        sources: superseding.sources.map((source) => ({
          document_id: source.document_id,
          page_number: source.page_number,
          excerpt: source.excerpt,
        })),
      },
      {
        onSuccess: (created) => {
          toast.push({
            tone: "success",
            title: `Revision ${created.revision} proposed`,
            description: "The original stays authoritative until the correction is verified.",
          });
          setSuperseding(null);
        },
        onError: (apiError) =>
          toast.push({
            tone: "error",
            title: "Could not supersede",
            description: apiError.message,
          }),
      },
    );
  };

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Facts"
          description="Extraction proposes; a person verifies. Nothing verifies itself."
          actions={
            <div className="flex items-center gap-1.5">
              {counts.PROPOSED > 0 ? (
                <Badge tone="warning">{counts.PROPOSED} awaiting review</Badge>
              ) : null}
              <Badge tone="success">{counts.VERIFIED} verified</Badge>
            </div>
          }
        />

        <div className="flex flex-wrap gap-1 border-b border-line-soft px-4 py-2">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={filter === item.key}
              onClick={() => setFilter(item.key)}
              className={cn(
                "rounded px-2.5 py-1 text-meta font-medium transition-colors duration-150",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
                filter === item.key
                  ? "bg-accent-700 text-white"
                  : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {isLoading ? <SkeletonRows rows={5} /> : null}
        <ErrorState
          error={error ? { message: error.message, status: error.status } : null}
          onRetry={() => refetch()}
        />
        {data && visible.length === 0 ? (
          <EmptyState
            title={filter === "ALL" ? "No facts yet" : `No ${filter.toLowerCase()} facts`}
            description={
              filter === "ALL"
                ? "Narrative sections cannot be drafted until facts are verified."
                : undefined
            }
          />
        ) : null}

        <ul className="divide-y divide-line-soft">
          {visible.map((fact) => (
            <FactRow
              key={fact.id}
              fact={fact}
              factsById={factsById}
              busy={busy}
              onVerify={handleVerify}
              onReject={(target) => {
                setRejecting(target);
                setRejectReason("");
              }}
              onSupersede={(target) => {
                setSuperseding(target);
                setSupersedeSummary(target.summary);
                setSupersedeReason("");
              }}
            />
          ))}
        </ul>
      </Panel>

      <Modal
        open={Boolean(rejecting)}
        onClose={() => setRejecting(null)}
        title="Reject this fact"
        description="Rejection is recorded with your name and reason. It cannot be undone."
        footer={
          <>
            <Button variant="secondary" onClick={() => setRejecting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={rejectReason.trim().length === 0 || reject.isPending}
              onClick={submitReject}
            >
              Reject fact
            </Button>
          </>
        }
      >
        <label className="block text-body font-medium text-ink-body" htmlFor="reject-reason">
          Reason
        </label>
        <textarea
          id="reject-reason"
          value={rejectReason}
          onChange={(event) => setRejectReason(event.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-body focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-accent-700"
          placeholder="Not supported by the records on file"
        />
        {rejecting ? <Note>“{rejecting.summary}”</Note> : null}
      </Modal>

      <Modal
        open={Boolean(superseding)}
        onClose={() => setSuperseding(null)}
        title="Supersede verified fact"
        description="The original is never edited. This creates a new revision that awaits its own verification."
        footer={
          <>
            <Button variant="secondary" onClick={() => setSuperseding(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={
                supersedeSummary.trim().length === 0 ||
                supersedeReason.trim().length === 0 ||
                supersede.isPending
              }
              onClick={submitSupersede}
            >
              Propose revision
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {superseding ? (
            <div className="rounded border border-line bg-surface-muted px-2 py-1.5">
              <p className="text-2xs font-medium uppercase tracking-[0.06em] text-ink-faint">
                Current, revision {superseding.revision}
              </p>
              <p className="mt-0.5 text-body text-ink-body">{superseding.summary}</p>
            </div>
          ) : null}

          <div>
            <label
              className="block text-body font-medium text-ink-body"
              htmlFor="supersede-summary"
            >
              Corrected statement
            </label>
            <textarea
              id="supersede-summary"
              value={supersedeSummary}
              onChange={(event) => setSupersedeSummary(event.target.value)}
              rows={3}
              className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-body"
            />
          </div>

          <div>
            <label className="block text-body font-medium text-ink-body" htmlFor="supersede-reason">
              Reason for the correction
            </label>
            <input
              id="supersede-reason"
              value={supersedeReason}
              onChange={(event) => setSupersedeReason(event.target.value)}
              className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-body"
              placeholder="Radiologist addendum corrected the measurement"
            />
          </div>

          <Note>
            The citations on the original are carried over. The correction is proposed, not
            verified — someone still has to review it.
          </Note>
        </div>
      </Modal>
    </div>
  );
}
