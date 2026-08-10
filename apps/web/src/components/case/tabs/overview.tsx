"use client";

import {
  useAccident,
  useClaim,
  useDamages,
  useFacts,
  useParties,
  useTimeline,
} from "@/lib/api/hooks";
import { formatDate, formatMoney, formatMoneyRange, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  LinkButton,
  Metric,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { WorkflowStatus } from "../workflow-status";
import type { TabProps } from "../workspace";

export function OverviewTab({
  caseId,
  demand,
  goToTab,
  validated = false,
  verifiedFactCount = 0,
}: TabProps) {
  const claim = useClaim(caseId);
  const accident = useAccident(caseId);
  const parties = useParties(caseId);
  const damages = useDamages(caseId);
  const timeline = useTimeline(caseId);
  const facts = useFacts(caseId);

  const verified = facts.data?.filter((fact) => fact.status === "VERIFIED") ?? [];
  const proposed = facts.data?.filter((fact) => fact.status === "PROPOSED") ?? [];
  const liabilityFacts = verified.filter((fact) => fact.fact_type === "liability");

  const treatmentEntries = timeline.data?.filter((entry) => entry.kind !== "collision") ?? [];
  const firstTreatment = treatmentEntries[0]?.entry_date ?? null;
  const lastTreatment = treatmentEntries[treatmentEntries.length - 1]?.entry_date ?? null;

  const insured = parties.data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "insured"),
  );
  const drivers = parties.data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "driver"),
  );

  return (
    <div className="space-y-4">
      <WorkflowStatus
        verifiedFactCount={verifiedFactCount || verified.length}
        demand={demand}
        validated={validated}
      />

      {/* ------------------------------------------------------ case summary */}
      <Panel>
        <PanelHeader
          title="Case summary"
          actions={<LinkButton onClick={() => goToTab("liability")}>Liability detail →</LinkButton>}
        />

        {accident.isLoading ? <SkeletonRows rows={3} /> : null}
        <ErrorState error={accident.error ? { message: accident.error.message } : null} />

        {accident.data === null && !accident.isLoading ? (
          <div className="px-4 py-4">
            <Note>No accident record has been entered for this case.</Note>
          </div>
        ) : null}

        {accident.data ? (
          <div className="grid gap-x-8 gap-y-4 px-4 py-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="min-w-0">
              <p className="eyebrow">Accident narrative of record</p>
              <p className="mt-1.5 max-w-[62ch] font-serif text-prose leading-[1.75] text-ink-body">
                {accident.data.description ?? "No narrative recorded."}
              </p>
              {accident.data.location ? (
                <p className="mt-2 text-meta text-ink-muted">{accident.data.location}</p>
              ) : null}
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-3.5 lg:border-l lg:border-line-soft lg:pl-8">
              <Field label="Date of loss">{formatDate(accident.data.occurred_on)}</Field>
              <Field label="Impact type">{humanize(accident.data.impact_type)}</Field>
              <Field label="Named insured">
                {insured && insured.length > 0
                  ? insured.map((party) => party.full_name).join(", ")
                  : "Not recorded"}
              </Field>
              <Field label="Driver">
                {drivers && drivers.length > 0
                  ? drivers.map((party) => party.full_name).join(", ")
                  : "Not recorded"}
              </Field>
              <Field label="Liability facts verified">
                <button
                  type="button"
                  onClick={() => goToTab("liability")}
                  className="rounded font-medium text-accent-700 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
                >
                  {liabilityFacts.length}
                </button>
              </Field>
              <Field label="Police report">{accident.data.police_report_number ?? "—"}</Field>
            </dl>
          </div>
        ) : null}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        {/* ---------------------------------------------------------- damages */}
        <Panel>
          <PanelHeader
            title="Damages"
            description="Computed by the backend from structured records."
            actions={<LinkButton onClick={() => goToTab("bills")}>Open bills →</LinkButton>}
          />

          {damages.isLoading ? <SkeletonRows rows={4} /> : null}
          <ErrorState error={damages.error ? { message: damages.error.message } : null} />

          {damages.data ? (
            <>
              <div className="grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4">
                <Metric
                  label="Known medical expenses"
                  value={formatMoney(damages.data.current_medical_expenses)}
                />
                <Metric
                  label="Future medical care"
                  value={formatMoneyRange(
                    damages.data.future_medical_low,
                    damages.data.future_medical_high,
                  )}
                />
                <Metric
                  label="General damages"
                  value={formatMoney(damages.data.general_damages)}
                  size="sm"
                />
                <Metric
                  label="Other structured damages"
                  value={formatMoney(damages.data.other_damages)}
                  size="sm"
                />
              </div>

              <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-line-soft bg-surface-muted px-4 py-3.5">
                <Metric
                  label="Known claimed total"
                  value={formatMoneyRange(
                    damages.data.known_claimed_damages_low,
                    damages.data.known_claimed_damages_high,
                  )}
                  size="lg"
                />
                <Metric
                  label="Policy limit"
                  value={formatMoney(claim.data?.policy_limit ?? null)}
                  size="lg"
                  hint={
                    claim.data && claim.data.policy_limit && !claim.data.policy_limit_confirmed
                      ? "Not confirmed against a declarations page"
                      : undefined
                  }
                  tone={
                    claim.data?.policy_limit && !claim.data.policy_limit_confirmed
                      ? "warn"
                      : "default"
                  }
                />
              </div>

              {damages.data.pending_bills.length > 0 ? (
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-warn-200 bg-warn-50 px-4 py-3">
                  <span className="metric-label text-warn-700">Pending bills</span>
                  <span className="tabular text-[1.0625rem] font-semibold text-warn-800">
                    {damages.data.pending_bills.length} outstanding
                  </span>
                  <span className="w-full text-meta leading-5 text-warn-800">
                    Pending charges are excluded from the known total. A bill with no amount on
                    file is never counted as zero.
                  </span>
                </div>
              ) : null}
            </>
          ) : null}
        </Panel>

        {/* -------------------------------------------------------- treatment */}
        <Panel>
          <PanelHeader
            title="Treatment"
            actions={
              <LinkButton onClick={() => goToTab("medical")}>View medical timeline →</LinkButton>
            }
          />

          {timeline.isLoading ? <SkeletonRows rows={3} /> : null}

          <div className="grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4">
            <Metric label="Timeline entries" value={timeline.data?.length ?? 0} size="sm" />
            <Metric label="Treatment events" value={treatmentEntries.length} size="sm" />
            <Metric label="First treatment" value={formatDate(firstTreatment)} size="sm" />
            <Metric label="Most recent treatment" value={formatDate(lastTreatment)} size="sm" />
          </div>

          <dl className="grid grid-cols-2 gap-x-6 gap-y-3.5 border-t border-line-soft px-4 py-3.5">
            <Field label="Parties on file">{parties.data?.length ?? 0}</Field>
            <Field label="Verified facts">
              <span className="font-medium">{verified.length}</span>
            </Field>
            <Field label="Awaiting review">
              {proposed.length > 0 ? (
                <button
                  type="button"
                  onClick={() => goToTab("facts")}
                  className="rounded"
                  aria-label="Open facts awaiting review"
                >
                  <Badge tone="warning">{proposed.length} proposed</Badge>
                </button>
              ) : (
                <span className="text-ink-muted">None</span>
              )}
            </Field>
            <Field label="Demand">
              {demand ? (
                <Badge tone={demand.locked ? "success" : "accent"}>
                  {humanize(demand.status)} · v{demand.version}
                </Badge>
              ) : (
                <span className="text-ink-muted">Not drafted</span>
              )}
            </Field>
          </dl>

          {!demand ? (
            <div className="border-t border-line-soft px-4 py-3">
              <Button size="sm" variant="primary" onClick={() => goToTab("demand")}>
                Start a demand draft
              </Button>
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
