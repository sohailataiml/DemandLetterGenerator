"use client";

import { useAccident, useFacts, useParties, useVehicles } from "@/lib/api/hooks";
import { formatDate, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FactStatusBadge,
  Field,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { useEvidence } from "../evidence";
import type { TabProps } from "../workspace";

export function LiabilityTab({ caseId }: TabProps) {
  const accident = useAccident(caseId);
  const parties = useParties(caseId);
  const vehicles = useVehicles(caseId);
  const facts = useFacts(caseId);
  const { show } = useEvidence();

  const liabilityFacts = facts.data?.filter((fact) => fact.fact_type === "liability") ?? [];
  const insured = parties.data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "insured"),
  );
  const drivers = parties.data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "driver"),
  );

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader title="Collision" />
        {accident.isLoading ? <SkeletonRows rows={3} /> : null}
        <ErrorState error={accident.error ? { message: accident.error.message } : null} />
        {accident.data === null ? (
          <EmptyState
            title="No accident record"
            description="Liability narrative cannot be drafted without one."
          />
        ) : null}
        {accident.data ? (
          <dl className="grid grid-cols-2 gap-4 px-4 py-3 sm:grid-cols-3">
            <Field label="Date">{formatDate(accident.data.occurred_on)}</Field>
            <Field label="Time">{accident.data.occurred_time ?? "—"}</Field>
            <Field label="Impact type">{humanize(accident.data.impact_type)}</Field>
            <Field label="Location" className="col-span-2 sm:col-span-3">
              {accident.data.location ?? "—"}
            </Field>
            <Field label="Narrative of record" className="col-span-2 sm:col-span-3">
              <p className="text-body leading-6 text-ink-body">
                {accident.data.description ?? "—"}
              </p>
            </Field>
            <Field label="Police report">{accident.data.police_report_number ?? "—"}</Field>
          </dl>
        ) : null}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="Who was involved" />
          <dl className="grid gap-4 px-4 py-3">
            <Field label="Named insured">
              {insured && insured.length > 0
                ? insured.map((party) => party.full_name).join(", ")
                : "Not recorded"}
            </Field>
            <Field label="Driver at time of collision">
              {drivers && drivers.length > 0
                ? drivers.map((party) => party.full_name).join(", ")
                : "Not recorded"}
            </Field>
          </dl>
          <div className="border-t border-line px-4 py-2.5">
            <Note>
              These are separate roles by design. Where they differ, the letter names each in its
              own right rather than treating them as one person.
            </Note>
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Vehicles" />
          {vehicles.isLoading ? <SkeletonRows rows={2} /> : null}
          {vehicles.data && vehicles.data.length === 0 ? (
            <EmptyState
              title="No vehicles recorded"
              description="Vehicle records have not been entered for this case."
            />
          ) : null}
          {vehicles.data && vehicles.data.length > 0 ? (
            <ul className="divide-y divide-line-soft">
              {vehicles.data.map((vehicle) => (
                <li key={vehicle.id} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-body text-ink-body">
                    {[vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(" ") ||
                      "Unspecified vehicle"}
                  </span>
                  {vehicle.is_client_vehicle ? <Badge tone="accent">Client vehicle</Badge> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      </div>

      <Panel>
        <PanelHeader
          title="Liability facts"
          description="Only verified facts reach the generated liability narrative."
        />
        {facts.isLoading ? <SkeletonRows rows={3} /> : null}
        {liabilityFacts.length === 0 && !facts.isLoading ? (
          <EmptyState
            title="No liability facts on file"
            description="The liability section cannot be drafted until at least one is verified."
          />
        ) : null}
        <ul className="divide-y divide-line-soft">
          {liabilityFacts.map((fact) => (
            <li key={fact.id} className="flex items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <FactStatusBadge status={fact.status} />
                  {fact.sources.length > 0 ? (
                    <span className="text-2xs text-ink-faint">
                      {fact.sources.length} citation{fact.sources.length === 1 ? "" : "s"}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-body leading-6 text-ink-body">{fact.summary}</p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => show({ kind: "fact", factId: fact.id })}
              >
                View source
              </Button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
