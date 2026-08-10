"use client";

import { cn } from "@/lib/cn";
import type { Demand } from "@/lib/api/types";

/**
 * Evidence → Draft → Validate → Approve.
 *
 * Every stage reflects a state the backend actually reports — verified fact
 * count, generation timestamp, persisted validation issues, the approval lock.
 * Nothing here is inferred.
 */

type StageState = "done" | "active" | "blocked" | "pending";

interface Stage {
  label: string;
  detail: string;
  state: StageState;
}

const DOT: Record<StageState, string> = {
  done: "bg-ok-600",
  active: "bg-accent-600",
  blocked: "bg-stop-600",
  pending: "bg-line-strong",
};

const DETAIL_TONE: Record<StageState, string> = {
  done: "text-ok-700",
  active: "text-accent-800",
  blocked: "text-stop-700",
  pending: "text-ink-faint",
};

export function buildStages({
  verifiedFactCount,
  demand,
  validated,
}: {
  verifiedFactCount: number;
  demand: Demand | undefined;
  validated: boolean;
}): Stage[] {
  const blocking = demand?.issues.filter((issue) => issue.severity === "BLOCKING").length ?? 0;
  const generated = Boolean(demand?.generated_at && demand.sections.length > 0);

  return [
    {
      label: "Evidence",
      detail: `${verifiedFactCount} verified fact${verifiedFactCount === 1 ? "" : "s"}`,
      state: verifiedFactCount > 0 ? "done" : "pending",
    },
    {
      label: "Draft",
      detail: !demand ? "Not created" : generated ? "Generated" : "Not generated",
      state: generated ? "done" : demand ? "active" : "pending",
    },
    {
      label: "Validate",
      detail: !validated
        ? "Not run"
        : blocking > 0
          ? `${blocking} blocking`
          : "Passed",
      state: !validated ? "pending" : blocking > 0 ? "blocked" : "done",
    },
    {
      label: "Approve",
      detail: demand?.locked
        ? `Approved · v${demand.version}`
        : blocking > 0
          ? "Blocked"
          : validated && generated
            ? "Ready"
            : "Not approved",
      state: demand?.locked ? "done" : blocking > 0 ? "blocked" : "pending",
    },
  ];
}

export function WorkflowStatus({
  verifiedFactCount,
  demand,
  validated,
  className,
}: {
  verifiedFactCount: number;
  demand: Demand | undefined;
  validated: boolean;
  className?: string;
}) {
  const stages = buildStages({ verifiedFactCount, demand, validated });

  return (
    <section
      aria-label="Case workflow"
      className={cn("card flex flex-wrap items-stretch overflow-hidden", className)}
    >
      {stages.map((stage, index) => (
        <div
          key={stage.label}
          className={cn(
            "flex min-w-[9.5rem] flex-1 items-center gap-2.5 px-4 py-2.5",
            index > 0 && "border-l border-line-soft",
          )}
        >
          <span
            aria-hidden
            className={cn("h-2 w-2 shrink-0 rounded-full", DOT[stage.state])}
          />
          <span className="min-w-0">
            <span className="block metric-label">{stage.label}</span>
            <span
              className={cn("block truncate text-meta font-medium", DETAIL_TONE[stage.state])}
            >
              {stage.detail}
            </span>
          </span>
          {index < stages.length - 1 ? (
            <span aria-hidden className="ml-auto hidden text-ink-faint lg:inline">
              →
            </span>
          ) : null}
        </div>
      ))}
    </section>
  );
}
