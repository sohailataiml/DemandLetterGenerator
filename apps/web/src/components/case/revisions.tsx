"use client";

/**
 * Ask the model to revise a section, then decide on the result.
 *
 * Nothing in this component changes the letter. Requesting a revision returns a
 * proposal and a diff; the section still says what it said. Accepting is a
 * separate, attributed action that only an attorney may take, and the server
 * re-checks the constraints at that moment — the button here does not decide
 * anything.
 */

import { useState } from "react";

import { useAcceptRevision, useProposeRevision, useRejectRevision, useRevisions } from "@/lib/api/hooks";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Disclosure,
  Note,
  Panel,
  PanelHeader,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import type { RevisionProposalDetail, RevisionStatus } from "@/lib/api/types";

const STATUS_TONE: Record<RevisionStatus, "success" | "warning" | "danger" | "muted" | "accent"> = {
  PROPOSED: "accent",
  ACCEPTED: "success",
  REJECTED: "muted",
  INVALID: "danger",
  SUPERSEDED: "muted",
};

/** A unified diff, rendered line by line with the usual +/- semantics. */
export function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n").filter((line) => line.length > 0);
  if (lines.length === 0) {
    return <Note>The proposed text is identical to the current text.</Note>;
  }
  return (
    <pre
      data-testid="revision-diff"
      className="overflow-x-auto rounded border border-line bg-surface-muted p-3 text-2xs leading-5"
    >
      {lines.map((line, index) => {
        const isAdd = line.startsWith("+") && !line.startsWith("+++");
        const isRemove = line.startsWith("-") && !line.startsWith("---");
        const isMeta = line.startsWith("@@") || line.startsWith("+++") || line.startsWith("---");
        return (
          <div
            key={index}
            className={cn(
              "whitespace-pre-wrap",
              isAdd && "bg-ok-50 text-ok-700",
              isRemove && "bg-stop-50 text-stop-700",
              isMeta && "text-ink-faint",
            )}
          >
            {line}
          </div>
        );
      })}
    </pre>
  );
}

export function RevisionPanel({
  caseId,
  demandId,
  sectionKey,
  sectionTitle,
  locked,
  canAccept,
}: {
  caseId: string;
  demandId: string;
  sectionKey: string;
  sectionTitle: string;
  locked: boolean;
  canAccept: boolean;
}) {
  const [instruction, setInstruction] = useState("");
  const [proposal, setProposal] = useState<RevisionProposalDetail | null>(null);
  const [preserveAmounts, setPreserveAmounts] = useState(true);
  const [preserveDates, setPreserveDates] = useState(true);
  const [preserveFacts, setPreserveFacts] = useState(true);

  const propose = useProposeRevision(caseId);
  const accept = useAcceptRevision(caseId);
  const reject = useRejectRevision(caseId);
  const history = useRevisions(demandId);
  const toast = useToast();

  const submit = () => {
    if (!instruction.trim()) return;
    propose.mutate(
      {
        demandId,
        section_key: sectionKey,
        instruction: instruction.trim(),
        constraints: {
          preserve_amounts: preserveAmounts,
          preserve_dates: preserveDates,
          preserve_facts: preserveFacts,
          allow_new_facts: false,
        },
      },
      {
        onSuccess: (detail) => {
          setProposal(detail);
          toast.push({
            tone: detail.valid ? "success" : "error",
            title: detail.valid ? "Revision proposed" : "Revision rejected by validation",
            description: detail.valid
              ? "Nothing has changed yet — review the diff and accept or reject."
              : detail.violations[0]?.message,
          });
        },
        onError: (error) =>
          toast.push({ tone: "error", title: "Could not propose", description: error.message }),
      },
    );
  };

  const onAccept = () => {
    if (!proposal) return;
    accept.mutate(
      { proposalId: proposal.proposal.id },
      {
        onSuccess: () => {
          setProposal(null);
          setInstruction("");
          toast.push({ tone: "success", title: "Revision applied" });
        },
        onError: (error) =>
          toast.push({ tone: "error", title: "Not applied", description: error.message }),
      },
    );
  };

  const onReject = () => {
    if (!proposal) return;
    reject.mutate(
      { proposalId: proposal.proposal.id },
      {
        onSuccess: () => {
          setProposal(null);
          toast.push({ tone: "success", title: "Revision rejected" });
        },
      },
    );
  };

  const sectionHistory = (history.data ?? []).filter((item) => item.section_key === sectionKey);

  return (
    <Panel>
      <PanelHeader
        title={`Refine “${sectionTitle}” with AI`}
        description="The model proposes a change. It does not make one — you decide, and the server re-checks the constraints when you do."
        dense
      />
      <div className="space-y-3 px-4 py-3">
        <label className="block">
          <span className="metric-label">Instruction</span>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            disabled={locked}
            rows={2}
            placeholder="Make the liability section more forceful without changing any facts."
            className="mt-1 w-full rounded border border-line-strong bg-white px-2.5 py-1.5 text-meta text-ink focus:outline focus:outline-2 focus:outline-offset-0 focus:outline-accent-600 disabled:bg-surface-muted"
          />
        </label>

        <fieldset className="flex flex-wrap gap-x-4 gap-y-1.5">
          <legend className="metric-label">Constraints enforced in code</legend>
          {[
            ["Preserve amounts", preserveAmounts, setPreserveAmounts] as const,
            ["Preserve dates", preserveDates, setPreserveDates] as const,
            ["Preserve facts", preserveFacts, setPreserveFacts] as const,
          ].map(([label, value, set]) => (
            <label key={label} className="inline-flex items-center gap-1.5 text-meta text-ink-body">
              <input
                type="checkbox"
                checked={value}
                disabled={locked}
                onChange={(event) => set(event.target.checked)}
                className="rounded border-line-strong"
              />
              {label}
            </label>
          ))}
        </fieldset>

        <Button
          variant="primary"
          size="sm"
          disabled={locked || propose.isPending || !instruction.trim()}
          onClick={submit}
        >
          {propose.isPending ? "Drafting…" : "Propose revision"}
        </Button>

        {locked ? <Note>This demand is approved and locked. No revision can be applied.</Note> : null}

        {proposal ? (
          <div className="space-y-2.5 rounded border border-line bg-surface-muted p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={proposal.valid ? "success" : "danger"} strong>
                {proposal.valid ? "Passes constraints" : "Violates constraints"}
              </Badge>
              <span className="text-2xs text-ink-faint">
                {proposal.proposal.provider_name}
                {proposal.proposal.model_name ? ` · ${proposal.proposal.model_name}` : ""}
              </span>
              <Badge tone="warning">Not applied</Badge>
            </div>

            {proposal.violations.length > 0 ? (
              <ul className="space-y-1">
                {proposal.violations.map((violation) => (
                  <li key={violation.code} className="text-meta text-stop-700">
                    <span className="font-semibold">{violation.code}</span> — {violation.message}
                  </li>
                ))}
              </ul>
            ) : null}

            <DiffView diff={proposal.unified_diff} />

            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={!proposal.valid || !canAccept || accept.isPending}
                onClick={onAccept}
                title={
                  canAccept ? undefined : "Only an attorney may apply an AI revision."
                }
              >
                {accept.isPending ? "Applying…" : "Accept"}
              </Button>
              <Button size="sm" onClick={onReject} disabled={reject.isPending}>
                Reject
              </Button>
              <Button size="sm" onClick={submit} disabled={propose.isPending}>
                Regenerate
              </Button>
            </div>
            {!canAccept ? (
              <Note>Only an attorney may apply an AI revision to the letter.</Note>
            ) : null}
          </div>
        ) : null}

        {sectionHistory.length > 0 ? (
          <Disclosure summary={`Revision history (${sectionHistory.length})`}>
            <ul className="space-y-2">
              {sectionHistory.map((item) => (
                <li key={item.id} className="text-meta">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={STATUS_TONE[item.status]} strong>
                      {item.status}
                    </Badge>
                    <span className="text-2xs text-ink-faint">
                      {item.requested_by} · {formatDateTime(item.created_at)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-ink-body">{item.instruction}</p>
                  {item.decided_by ? (
                    <p className="mt-0.5 text-2xs text-ink-faint">
                      Decided by {item.decided_by}
                      {item.decision_note ? ` — ${item.decision_note}` : ""}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </Disclosure>
        ) : null}
      </div>
    </Panel>
  );
}
