"use client";

import { useState } from "react";

import { useSettlementTerms, useValidateDemand } from "@/lib/api/hooks";
import { apiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  Note,
  Panel,
  PanelHeader,
} from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { ValidationIssueList } from "../validation-list";
import type { TabProps } from "../workspace";

/** Resolution path for the expiration-date rules, which is the one blocking
 *  issue a reviewer can fix from this screen. */
function ExpirationDialog({
  caseId,
  open,
  onClose,
  onSaved,
}: {
  caseId: string;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const settlement = useSettlementTerms(caseId);
  const toast = useToast();
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const current = settlement.data;
  const initial = current ? current.expires_at.slice(0, 16) : "";

  const save = async () => {
    if (!current) return;
    setSaving(true);
    try {
      await apiFetch(`/v1/cases/${caseId}/settlement-terms`, {
        method: "PUT",
        body: {
          expires_at: new Date(value || initial).toISOString(),
          demand_type: current.demand_type,
          demand_amount: current.demand_amount,
          demand_is_policy_limits: current.demand_is_policy_limits,
          delivery_method: current.delivery_method,
          conditions: current.conditions,
        },
      });
      toast.push({
        tone: "success",
        title: "Expiration updated",
        description: "Regenerate the demand and re-run validation.",
      });
      onSaved();
      onClose();
    } catch (error) {
      toast.push({
        tone: "error",
        title: "Could not update",
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit demand expiration"
      description="The expiration must fall after the letter date, and every reference to it in the letter must agree."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={saving || !current} onClick={save}>
            {saving ? "Saving…" : "Save expiration"}
          </Button>
        </>
      }
    >
      {current ? (
        <div className="space-y-3">
          <p className="text-body text-ink-muted">
            Currently {formatDateTime(current.expires_at)}.
          </p>
          <div>
            <label className="block text-body font-medium text-ink-body" htmlFor="expires-at">
              New expiration
            </label>
            <input
              id="expires-at"
              type="datetime-local"
              defaultValue={initial}
              onChange={(event) => setValue(event.target.value)}
              className="mt-1 rounded border border-line-strong px-2 py-1.5 text-body"
            />
          </div>
          <Note>
            Changing the expiration does not rewrite the letter. Regenerate the demand so the
            deterministic sections pick up the new date, then validate again.
          </Note>
        </div>
      ) : (
        <Note>No settlement terms are on file for this case.</Note>
      )}
    </Modal>
  );
}

export function ValidationTab({
  caseId,
  demand,
  goToTab,
  onValidated,
}: TabProps & { onValidated?: () => void }) {
  const validate = useValidateDemand(caseId);
  const toast = useToast();
  const [editingExpiration, setEditingExpiration] = useState(false);

  if (!demand) {
    return (
      <Panel>
        <PanelHeader title="Validation" />
        <EmptyState
          title="No demand to validate"
          description="Create a demand draft first."
          action={<Button onClick={() => goToTab("demand")}>Go to demand</Button>}
        />
      </Panel>
    );
  }

  const issues = demand.issues;
  const blocking = issues.filter((issue) => issue.severity === "BLOCKING").length;
  const warning = issues.filter((issue) => issue.severity === "WARNING").length;
  const info = issues.filter((issue) => issue.severity === "INFO").length;

  const run = () =>
    validate.mutate(demand.id, {
      onSuccess: (result) => {
        onValidated?.();
        const nextBlocking = result.filter((issue) => issue.severity === "BLOCKING").length;
        toast.push({
          tone: nextBlocking > 0 ? "error" : "success",
          title:
            nextBlocking > 0
              ? `${nextBlocking} blocking issue(s)`
              : "Clean — no blocking issues",
          description: `${result.length} issue(s) recorded.`,
        });
      },
      onError: (error) =>
        toast.push({ tone: "error", title: "Validation failed", description: error.message }),
    });

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Validation"
          description="Deterministic checks over the case data and the generated letter."
          actions={
            <Button variant="primary" size="sm" onClick={run} disabled={validate.isPending}>
              {validate.isPending ? "Running…" : "Run validation"}
            </Button>
          }
        />

        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
          <Badge tone={blocking > 0 ? "danger" : "success"}>{blocking} blocking</Badge>
          <Badge tone={warning > 0 ? "warning" : "muted"}>{warning} warning</Badge>
          <Badge tone="muted">{info} info</Badge>
          {demand.locked ? <Badge tone="success">Approved and locked</Badge> : null}
        </div>

        <div className="px-4 py-4">
          {issues.length === 0 ? (
            <EmptyState
              title="No issues recorded"
              description="Either validation has not run against this draft, or the last run was clean. Approval re-runs it either way."
              action={<Button onClick={run}>Run validation</Button>}
            />
          ) : (
            <ValidationIssueList
              issues={issues}
              actions={{
                onOpenSection: (sectionKey) => goToTab("demand", sectionKey),
                onOpenParties: () => goToTab("parties"),
                onOpenBills: () => goToTab("bills"),
                onOpenFacts: () => goToTab("facts"),
                onEditExpiration: () => setEditingExpiration(true),
              }}
            />
          )}
        </div>

        <div className="border-t border-line px-4 py-2.5">
          <Note>
            A BLOCKING issue prevents approval outright. The backend re-runs every rule at the
            moment of approval, so this page is a working view, never the authority.
          </Note>
        </div>
      </Panel>

      <ExpirationDialog
        caseId={caseId}
        open={editingExpiration}
        onClose={() => setEditingExpiration(false)}
        onSaved={() => undefined}
      />
    </div>
  );
}
