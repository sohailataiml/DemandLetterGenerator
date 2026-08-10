"use client";

import Link from "next/link";

import { useDamages, useFacts } from "@/lib/api/hooks";
import { formatDate, formatDateTime, formatMoney, formatMoneyRange } from "@/lib/format";
import { Badge, Skeleton } from "@/components/ui/primitives";
import { FinalDocumentActions } from "./demand-actions";
import type { CaseRecord, Claim, Demand, SettlementTerms } from "@/lib/api/types";

/** One cell of the summary strip under the case identity. */
function HeaderMetric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "default" | "ok" | "warn" | "stop" | "muted";
}) {
  const toneClass = {
    default: "text-ink",
    ok: "text-ok-700",
    warn: "text-warn-700",
    stop: "text-stop-700",
    muted: "text-ink-faint",
  }[tone];

  return (
    <div className="min-w-0 px-4 py-2.5 first:pl-0">
      <p className="metric-label">{label}</p>
      <p className={`tabular mt-0.5 truncate text-[1.0625rem] font-semibold tracking-tight ${toneClass}`}>
        {value}
      </p>
    </div>
  );
}

/** Demand state, said plainly: APPROVED, NEEDS REVIEW, DRAFT, or no demand. */
function DemandStatusBadge({
  demand,
  validated,
}: {
  demand: Demand | undefined;
  validated: boolean;
}) {
  if (!demand) {
    return (
      <Badge tone="muted" strong>
        No demand
      </Badge>
    );
  }
  if (demand.locked) {
    return (
      <Badge tone="success" strong>
        Approved · v{demand.version}
      </Badge>
    );
  }
  const blocking = demand.issues.filter((issue) => issue.severity === "BLOCKING").length;
  if (validated && blocking > 0) {
    return (
      <Badge tone="danger" strong>
        Needs review · {blocking} blocking
      </Badge>
    );
  }
  return (
    <Badge tone="accent" strong>
      Draft · v{demand.version}
    </Badge>
  );
}

export function CaseHeader({
  caseId,
  caseRecord,
  claim,
  settlement,
  demand,
  loading,
  validated,
  onValidationClick,
  onOpenDemand,
}: {
  caseId: string;
  caseRecord: CaseRecord | undefined;
  claim: Claim | null | undefined;
  settlement: SettlementTerms | null | undefined;
  demand: Demand | undefined;
  loading: boolean;
  /** True once a validation run has been recorded for this demand. */
  validated: boolean;
  onValidationClick: () => void;
  onOpenDemand: () => void;
}) {
  const damages = useDamages(caseId);
  const facts = useFacts(caseId);

  const verifiedCount = facts.data?.filter((fact) => fact.status === "VERIFIED").length ?? 0;
  const blocking = demand?.issues.filter((issue) => issue.severity === "BLOCKING").length ?? 0;

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto max-w-workspace px-6">
        <div className="pt-3">
          <Link
            href="/"
            className="text-meta text-ink-faint transition-colors hover:text-accent-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
          >
            ← All cases
          </Link>
        </div>

        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 pt-1.5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <h1 className="text-case font-semibold text-ink">
                {loading && !caseRecord ? (
                  <Skeleton className="h-7 w-56" />
                ) : (
                  (caseRecord?.client_display_name ?? "Case")
                )}
              </h1>
              <DemandStatusBadge demand={demand} validated={validated} />
            </div>

            <p className="mt-1.5 text-body text-ink-muted">
              {claim ? (
                <>
                  Claim <span className="tabular font-medium text-ink-body">{claim.claim_number}</span>
                  <span className="px-1.5 text-ink-faint">·</span>
                  Date of loss{" "}
                  <span className="font-medium text-ink-body">
                    {formatDate(claim.date_of_loss)}
                  </span>
                </>
              ) : (
                <span className="text-ink-faint">No claim on file</span>
              )}
            </p>

            <p className="mt-0.5 text-meta text-ink-muted">
              {claim?.carrier ? (
                <>
                  <span>{claim.carrier.name}</span>
                  {claim.carrier.adjuster_name ? (
                    <>
                      <span className="px-1.5 text-ink-faint">·</span>
                      Adjuster <span>{claim.carrier.adjuster_name}</span>
                    </>
                  ) : null}
                </>
              ) : (
                <span className="text-ink-faint">No carrier recorded</span>
              )}
              <span className="px-1.5 text-ink-faint">·</span>
              <span className="text-ink-faint">{caseRecord?.reference}</span>
            </p>
          </div>

          {demand?.locked ? (
            <FinalDocumentActions demand={demand} onView={onOpenDemand} />
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap divide-x divide-line-soft border-t border-line-soft">
          <HeaderMetric
            label="Claimed damages"
            value={
              damages.data
                ? formatMoneyRange(
                    damages.data.known_claimed_damages_low,
                    damages.data.known_claimed_damages_high,
                  )
                : "—"
            }
          />
          <HeaderMetric
            label="Policy limit"
            value={formatMoney(claim?.policy_limit ?? null)}
            tone={claim?.policy_limit && !claim.policy_limit_confirmed ? "warn" : "default"}
          />
          <HeaderMetric label="Verified facts" value={verifiedCount} />
          <HeaderMetric
            label="Validation"
            value={
              !demand ? (
                "—"
              ) : !validated ? (
                "Not run"
              ) : blocking > 0 ? (
                <button
                  type="button"
                  onClick={onValidationClick}
                  className="rounded underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
                >
                  {blocking} blocking
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onValidationClick}
                  className="rounded underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
                >
                  ✓ 0 blocking
                </button>
              )
            }
            tone={!validated ? "muted" : blocking > 0 ? "stop" : "ok"}
          />
          <HeaderMetric
            label="Demand expires"
            value={settlement ? formatDateTime(settlement.expires_at) : "—"}
          />
        </div>
      </div>
    </header>
  );
}
