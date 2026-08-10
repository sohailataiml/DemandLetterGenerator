"use client";

import { useParties } from "@/lib/api/hooks";
import { humanize } from "@/lib/format";
import {
  Badge,
  EmptyState,
  ErrorState,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { BadgeTone } from "@/components/ui/primitives";
import type { Party, PartyRole } from "@/lib/api/types";
import type { TabProps } from "../workspace";

const ROLE_TONE: Record<PartyRole, BadgeTone> = {
  client: "accent",
  insured: "warning",
  driver: "warning",
  vehicle_owner: "neutral",
  adjuster: "neutral",
  attorney: "neutral",
  witness: "neutral",
};

function PartyCard({ party }: { party: Party }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body font-medium text-ink">{party.full_name}</span>
        {party.role_assignments.map((assignment) => (
          <Badge key={assignment.role} tone={ROLE_TONE[assignment.role] ?? "neutral"}>
            {humanize(assignment.role)}
          </Badge>
        ))}
        {party.role_assignments.length === 0 ? <Badge tone="muted">No role recorded</Badge> : null}
      </div>

      {party.organization ? (
        <p className="mt-1 text-meta text-ink-muted">{party.organization}</p>
      ) : null}

      {party.role_assignments
        .filter((assignment) => assignment.relationship_note)
        .map((assignment) => (
          <p key={`${assignment.role}-note`} className="mt-1 text-meta leading-5 text-ink-muted">
            <span className="font-medium text-ink-body">{humanize(assignment.role)}:</span>{" "}
            {assignment.relationship_note}
          </p>
        ))}

      {party.email || party.phone ? (
        <p className="mt-1 text-meta text-ink-faint">
          {[party.email, party.phone].filter(Boolean).join(" · ")}
        </p>
      ) : null}
    </li>
  );
}

export function PartiesTab({ caseId }: TabProps) {
  const { data, isLoading, error, refetch } = useParties(caseId);

  const insured = data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "insured"),
  );
  const drivers = data?.filter((party) =>
    party.role_assignments.some((assignment) => assignment.role === "driver"),
  );
  const differ =
    insured &&
    drivers &&
    insured.length > 0 &&
    drivers.length > 0 &&
    !drivers.some((driver) => insured.some((person) => person.full_name === driver.full_name));

  return (
    <div className="space-y-4">
      {differ ? (
        <Panel className="border-warn-200 bg-warn-50/60">
          <div className="px-4 py-3">
            <h2 className="text-body font-semibold text-ink">
              Named insured and driver are different people
            </h2>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-2xs font-medium uppercase tracking-[0.06em] text-ink-faint">
                  Insured
                </p>
                <p className="text-body text-ink">
                  {insured!.map((party) => party.full_name).join(", ")}
                </p>
              </div>
              <div>
                <p className="text-2xs font-medium uppercase tracking-[0.06em] text-ink-faint">
                  Driver
                </p>
                <p className="text-body text-ink">
                  {drivers!.map((party) => party.full_name).join(", ")}
                </p>
              </div>
            </div>
            <Note>
              This is common and often legitimate — a permissive user, a family member, an
              employee. Names are shown exactly as recorded and are never reconciled automatically.
              What validation checks is that the relationship is documented.
            </Note>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader
          title="Parties"
          description="Insured, driver, and every other role are tracked separately. One person may hold several."
        />
        {isLoading ? <SkeletonRows rows={4} /> : null}
        <ErrorState
          error={error ? { message: error.message, status: error.status } : null}
          onRetry={() => refetch()}
        />
        {data && data.length === 0 ? (
          <EmptyState title="No parties recorded" description="Add parties through the API." />
        ) : null}
        {data && data.length > 0 ? (
          <ul className="divide-y divide-line-soft">
            {data.map((party) => (
              <PartyCard key={party.id} party={party} />
            ))}
          </ul>
        ) : null}
      </Panel>
    </div>
  );
}
