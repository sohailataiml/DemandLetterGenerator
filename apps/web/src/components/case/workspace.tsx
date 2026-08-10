"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  useCase,
  useCaseSummaries,
  useClaim,
  useDemands,
  useFacts,
  useSettlementTerms,
} from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { ErrorState, Skeleton } from "@/components/ui/primitives";
import { CaseHeader } from "./case-header";
import { EvidencePanel, EvidenceProvider, useEvidence } from "./evidence";
import { SectionContextRail } from "./section-context";
import { AuditTab } from "./tabs/audit";
import { BillsTab } from "./tabs/bills";
import { DemandTab } from "./tabs/demand";
import { DocumentsTab } from "./tabs/documents";
import { FactsTab } from "./tabs/facts";
import { LiabilityTab } from "./tabs/liability";
import { MedicalTab } from "./tabs/medical";
import { OverviewTab } from "./tabs/overview";
import { PartiesTab } from "./tabs/parties";
import { ValidationTab } from "./tabs/validation";
import { ValidationRail } from "./validation-rail";

/** The case file, then the review workflow — separated visually in the nav. */
const NAV_GROUPS = [
  {
    label: null,
    items: [
      { key: "overview", label: "Overview" },
      { key: "parties", label: "Parties" },
      { key: "liability", label: "Liability" },
      { key: "medical", label: "Medical" },
      { key: "bills", label: "Bills" },
      { key: "facts", label: "Facts" },
      { key: "documents", label: "Documents" },
    ],
  },
  {
    label: "Review",
    items: [
      { key: "demand", label: "Demand" },
      { key: "validation", label: "Validation" },
      { key: "audit", label: "Audit" },
    ],
  },
] as const;

const TAB_KEYS = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.key));

export type TabKey = (typeof TAB_KEYS)[number];

function isTabKey(value: string | null): value is TabKey {
  return TAB_KEYS.some((key) => key === value);
}

function WorkspaceInner({ caseId }: { caseId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { selection, clear } = useEvidence();

  const tabParam = searchParams.get("tab");
  const activeTab: TabKey = isTabKey(tabParam) ? tabParam : "overview";
  const focusedSection = searchParams.get("section");

  const caseQuery = useCase(caseId);
  const claimQuery = useClaim(caseId);
  const settlementQuery = useSettlementTerms(caseId);
  const demandsQuery = useDemands(caseId);
  const summariesQuery = useCaseSummaries();
  const factsQuery = useFacts(caseId);

  // Latest demand version is the one under review.
  const demand = useMemo(() => demandsQuery.data?.[0], [demandsQuery.data]);
  const summary = summariesQuery.data?.find((item) => item.id === caseId);

  const [locallyValidated, setLocallyValidated] = useState(false);
  const validated = Boolean(summary?.validation?.last_validated_at) || locallyValidated;
  const verifiedFactCount =
    factsQuery.data?.filter((fact) => fact.status === "VERIFIED").length ?? 0;

  const goToTab = useCallback(
    (tab: TabKey, section?: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tab);
      if (section) params.set("section", section);
      else params.delete("section");
      router.replace(`/cases/${caseId}?${params.toString()}`, { scroll: false });
    },
    [caseId, router, searchParams],
  );

  if (caseQuery.error) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <ErrorState
          error={{ message: caseQuery.error.message, status: caseQuery.error.status }}
          onRetry={() => caseQuery.refetch()}
        />
      </div>
    );
  }

  const tabProps = { caseId, demand, goToTab, focusedSection, validated, verifiedFactCount };

  const issueCount = demand?.issues.length ?? 0;
  const showingSectionContext = activeTab === "demand" && Boolean(focusedSection) && Boolean(demand);
  // A clean validation result does not deserve a full column.
  const railIsCompact = !selection && !showingSectionContext && issueCount === 0;

  return (
    <div className="flex min-h-screen flex-col">
      <CaseHeader
        caseId={caseId}
        caseRecord={caseQuery.data}
        claim={claimQuery.data}
        settlement={settlementQuery.data}
        demand={demand}
        loading={caseQuery.isLoading}
        validated={validated}
        onValidationClick={() => goToTab("validation")}
        onOpenDemand={() => goToTab("demand")}
      />

      <div className="mx-auto flex w-full max-w-workspace min-h-0 flex-1">
        <nav
          aria-label="Case sections"
          className="w-[11.5rem] shrink-0 border-r border-line bg-white px-2 py-4"
        >
          {NAV_GROUPS.map((group, groupIndex) => (
            <div key={group.label ?? "case"} className={cn(groupIndex > 0 && "mt-5")}>
              {group.label ? (
                <p className="mb-1.5 px-2.5 eyebrow">{group.label}</p>
              ) : null}
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const isActive = item.key === activeTab;
                  const badge =
                    item.key === "validation" && demand && validated
                      ? demand.issues.filter((issue) => issue.severity === "BLOCKING").length
                      : 0;
                  return (
                    <li key={item.key}>
                      <button
                        type="button"
                        aria-current={isActive ? "page" : undefined}
                        onClick={() => goToTab(item.key)}
                        className={cn(
                          "nav-item",
                          isActive ? "nav-item-active" : "nav-item-idle",
                        )}
                      >
                        <span className="truncate">{item.label}</span>
                        {badge > 0 ? (
                          <span className="ml-auto rounded bg-stop-100 px-1.5 text-2xs font-semibold text-stop-700">
                            {badge}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <main className="min-w-0 flex-1 overflow-x-hidden bg-surface-muted px-5 py-5">
          {caseQuery.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            <>
              {activeTab === "overview" ? <OverviewTab {...tabProps} /> : null}
              {activeTab === "parties" ? <PartiesTab {...tabProps} /> : null}
              {activeTab === "liability" ? <LiabilityTab {...tabProps} /> : null}
              {activeTab === "medical" ? <MedicalTab {...tabProps} /> : null}
              {activeTab === "bills" ? <BillsTab {...tabProps} /> : null}
              {activeTab === "facts" ? <FactsTab {...tabProps} /> : null}
              {activeTab === "documents" ? <DocumentsTab {...tabProps} /> : null}
              {activeTab === "demand" ? (
                <DemandTab {...tabProps} onValidated={() => setLocallyValidated(true)} />
              ) : null}
              {activeTab === "validation" ? (
                <ValidationTab {...tabProps} onValidated={() => setLocallyValidated(true)} />
              ) : null}
              {activeTab === "audit" ? <AuditTab {...tabProps} /> : null}
            </>
          )}
        </main>

        <aside
          aria-label={selection ? "Source evidence" : "Case context"}
          className={cn(
            "hidden shrink-0 border-l border-line bg-white transition-[width] duration-150 xl:block",
            railIsCompact ? "w-[15.5rem]" : "w-[21.5rem]",
          )}
        >
          <div className="sticky top-0 max-h-screen overflow-y-auto">
            {selection ? (
              <EvidencePanel caseId={caseId} />
            ) : showingSectionContext && demand && focusedSection ? (
              <SectionContextRail
                caseId={caseId}
                demand={demand}
                sectionKey={focusedSection}
                onOpenValidation={() => goToTab("validation")}
              />
            ) : (
              <ValidationRail
                demand={demand}
                validated={validated}
                onOpenValidation={() => goToTab("validation")}
                onOpenSection={(sectionKey) => goToTab("demand", sectionKey)}
              />
            )}
          </div>
        </aside>
      </div>

      {/* Below xl the evidence panel becomes an overlay so it stays usable. */}
      {selection ? (
        <div className="fixed inset-y-0 right-0 z-30 w-full max-w-md border-l border-line bg-white shadow-overlay xl:hidden">
          <EvidencePanel caseId={caseId} />
        </div>
      ) : null}
      {selection ? (
        <div className="fixed inset-0 z-20 bg-ink/20 xl:hidden" onClick={clear} aria-hidden />
      ) : null}
    </div>
  );
}

export function CaseWorkspace({ caseId }: { caseId: string }) {
  return (
    <EvidenceProvider>
      <WorkspaceInner caseId={caseId} />
    </EvidenceProvider>
  );
}

export interface TabProps {
  caseId: string;
  demand: import("@/lib/api/types").Demand | undefined;
  goToTab: (tab: TabKey, section?: string) => void;
  focusedSection: string | null;
  validated?: boolean;
  verifiedFactCount?: number;
}
