"use client";

import { useEffect, useRef, useState } from "react";

import {
  useCase,
  useCreateDemand,
  useDemands,
  useDocuments,
  useEditSection,
  useFacts,
  useGenerateDemand,
  useValidateDemand,
  useApproveDemand,
} from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate, formatDateTime, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { AUTH_USER_ROLE } from "@/lib/api/client";
import { useDemandDownloads } from "../demand-actions";
import { BlockedApprovalPanel, DemandReadiness, PipelineStrip } from "../readiness";
import { RevisionPanel } from "../revisions";
import type { DemandSection, ValidationIssue } from "@/lib/api/types";
import type { TabProps } from "../workspace";

/** Sections the template renders as fixed blocks rather than prose. */
const BLOCK_SECTIONS = new Set([
  "header",
  "claim_metadata",
  "medical_expense_summary",
  "future_medical",
  "signature",
  "conditions",
]);

const SOURCE_TONE = {
  template: "muted",
  ai: "accent",
  human: "warning",
} as const;

const SOURCE_LABEL = {
  template: "Deterministic",
  ai: "Generated draft",
  human: "Attorney edited",
} as const;

function SectionCard({
  section,
  issues,
  selected,
  locked,
  onSelect,
  onSave,
  onRegenerate,
  saving,
  regenerating,
}: {
  section: DemandSection;
  issues: ValidationIssue[];
  selected: boolean;
  locked: boolean;
  onSelect: () => void;
  onSave: (body: string) => void;
  onRegenerate: () => void;
  saving: boolean;
  regenerating: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(section.body);
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setDraft(section.body);
  }, [section.body]);

  useEffect(() => {
    if (selected) cardRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  const blocking = issues.filter((issue) => issue.severity === "BLOCKING").length;
  const warning = issues.filter((issue) => issue.severity === "WARNING").length;
  const undrafted = section.body.trim().startsWith("[");

  return (
    <article
      ref={cardRef}
      id={`demand-section-${section.key}`}
      aria-labelledby={`section-${section.key}`}
      onClick={onSelect}
      className={cn(
        "group scroll-mt-6 border-l-[3px] px-8 py-6 transition-colors duration-150",
        selected
          ? "border-l-accent-600 bg-accent-50/40"
          : "border-l-transparent hover:bg-surface-muted/60",
        blocking > 0 && !selected && "border-l-stop-200",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3 id={`section-${section.key}`} className="letter-heading">
          {section.title}
        </h3>
        <Badge tone={SOURCE_TONE[section.source]}>{SOURCE_LABEL[section.source]}</Badge>
        {section.used_fact_ids.length > 0 ? (
          <Badge tone="neutral">
            {section.used_fact_ids.length} fact
            {section.used_fact_ids.length === 1 ? "" : "s"}
          </Badge>
        ) : null}
        {blocking > 0 ? (
          <Badge tone="danger" strong>
            {blocking} blocking
          </Badge>
        ) : null}
        {warning > 0 ? <Badge tone="warning">{warning} warning</Badge> : null}
      </div>

      {editing ? (
        <div className="mt-3">
          <label className="sr-only" htmlFor={`edit-${section.key}`}>
            Edit {section.title}
          </label>
          <textarea
            id={`edit-${section.key}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={Math.min(24, Math.max(5, draft.split("\n").length + 1))}
            className="w-full rounded border border-line-strong bg-white p-3 font-mono text-[0.8125rem] leading-6 text-ink-body"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={saving}
              onClick={(event) => {
                event.stopPropagation();
                onSave(draft);
                setEditing(false);
              }}
            >
              Save edit
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={(event) => {
                event.stopPropagation();
                setDraft(section.body);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
            <Note>Saving marks this section attorney-edited. Re-run validation afterwards.</Note>
          </div>
        </div>
      ) : (
        <div
          className={cn(
            "mt-3",
            BLOCK_SECTIONS.has(section.key) ? "letter-block" : "letter-body max-w-letter",
            undrafted &&
              "rounded border border-warn-200 bg-warn-50 p-3 font-sans text-meta leading-6 text-warn-800",
          )}
        >
          {section.body || <span className="text-ink-faint">Empty section</span>}
        </div>
      )}

      {!locked && !editing ? (
        <div className="mt-3 flex flex-wrap gap-2 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover:opacity-100">
          <Button
            size="sm"
            variant="ghost"
            onClick={(event) => {
              event.stopPropagation();
              setEditing(true);
            }}
          >
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={regenerating}
            onClick={(event) => {
              event.stopPropagation();
              onRegenerate();
            }}
          >
            Regenerate section
          </Button>
        </div>
      ) : null}
    </article>
  );
}

export function DemandTab({
  caseId,
  demand,
  goToTab,
  focusedSection,
  onValidated,
}: TabProps & { onValidated?: () => void }) {
  const caseQuery = useCase(caseId);
  const demandsQuery = useDemands(caseId);
  const factsQuery = useFacts(caseId);
  const documentsQuery = useDocuments(caseId);
  const createDemand = useCreateDemand(caseId);
  const generate = useGenerateDemand(caseId);
  const validate = useValidateDemand(caseId);
  const approve = useApproveDemand(caseId);
  const editSection = useEditSection(caseId);
  const toast = useToast();
  const downloads = useDemandDownloads(demand?.id);

  const [confirmingApproval, setConfirmingApproval] = useState(false);
  const [acknowledgement, setAcknowledgement] = useState("");
  const [approvalIssues, setApprovalIssues] = useState<
    { code: string; message: string; section_key: string | null }[]
  >([]);

  const selectSection = (key: string) => goToTab("demand", key);

  if (demandsQuery.isLoading) return <SkeletonRows rows={8} />;
  if (demandsQuery.error) {
    return (
      <ErrorState
        error={{ message: demandsQuery.error.message, status: demandsQuery.error.status }}
        onRetry={() => demandsQuery.refetch()}
      />
    );
  }

  if (!demand) {
    return (
      <Panel>
        <PanelHeader title="Demand letter" />
        <EmptyState
          title="No demand drafted"
          description="Create a draft, then generate it from the verified facts on file."
          action={
            <Button
              variant="primary"
              disabled={createDemand.isPending}
              onClick={() =>
                createDemand.mutate(
                  {},
                  {
                    onSuccess: (created) =>
                      generate.mutate(
                        { demandId: created.id },
                        {
                          onSuccess: () =>
                            toast.push({ tone: "success", title: "Draft generated" }),
                          onError: (error) =>
                            toast.push({
                              tone: "error",
                              title: "Generation failed",
                              description: error.message,
                            }),
                        },
                      ),
                    onError: (error) =>
                      toast.push({
                        tone: "error",
                        title: "Could not create draft",
                        description: error.message,
                      }),
                  },
                )
              }
            >
              Create and generate draft
            </Button>
          }
        />
      </Panel>
    );
  }

  const issuesFor = (key: string) => demand.issues.filter((issue) => issue.section_key === key);
  const blockingCount = demand.issues.filter((issue) => issue.severity === "BLOCKING").length;

  const runValidation = () =>
    validate.mutate(demand.id, {
      onSuccess: (issues) => {
        onValidated?.();
        const blocking = issues.filter((issue) => issue.severity === "BLOCKING").length;
        toast.push({
          tone: blocking > 0 ? "error" : "success",
          title: blocking > 0 ? `${blocking} blocking issue(s)` : "No blocking issues",
          description:
            blocking > 0
              ? "Approval stays closed until these are resolved."
              : `${issues.length} issue(s) recorded in total.`,
        });
      },
      onError: (error) =>
        toast.push({ tone: "error", title: "Validation failed", description: error.message }),
    });

  const submitApproval = () => {
    setApprovalIssues([]);
    approve.mutate(
      { demandId: demand.id, acknowledgement },
      {
        onSuccess: (approved) => {
          setConfirmingApproval(false);
          setAcknowledgement("");
          toast.push({
            tone: "success",
            title: `Demand approved · v${approved.version}`,
            description: approved.docx_sha256
              ? `Locked bytes SHA-256 ${approved.docx_sha256.slice(0, 12)}…`
              : undefined,
          });
        },
        onError: (error) => {
          onValidated?.();
          if (error.isConflict) {
            setApprovalIssues(error.blockingIssues);
            toast.push({ tone: "error", title: "Approval refused", description: error.message });
            return;
          }
          toast.push({ tone: "error", title: "Approval failed", description: error.message });
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <PipelineStrip
        demand={demand}
        facts={factsQuery.data ?? []}
        documentCount={documentsQuery.data?.length ?? 0}
      />
      <DemandReadiness
        demand={demand}
        facts={factsQuery.data ?? []}
        issues={demand.issues}
        isLoading={factsQuery.isLoading}
      />
      <BlockedApprovalPanel
        issues={demand.issues}
        onNavigate={(issue) => issue.section_key && selectSection(issue.section_key)}
      />
      <Panel>
        <PanelHeader
          title={`Demand letter · version ${demand.version}`}
          description={
            demand.generated_at
              ? `Generated ${formatDateTime(demand.generated_at)} · template ${
                  demand.template_version ?? "—"
                } · drafter ${demand.provider_name ?? "—"}${
                  demand.model_name ? ` (${demand.model_name})` : ""
                }`
              : "Not generated yet."
          }
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={runValidation} disabled={validate.isPending}>
                {validate.isPending ? "Validating…" : "Validate demand"}
              </Button>
              <Button size="sm" onClick={downloads.downloadDocx} disabled={downloads.busy === "docx"}>
                {demand.locked ? "Download DOCX" : "Generate DOCX"}
              </Button>
              <Button size="sm" onClick={downloads.downloadPdf} disabled={downloads.busy === "pdf"}>
                {demand.locked ? "Download PDF" : "Generate PDF"}
              </Button>
              {!demand.locked ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setApprovalIssues([]);
                    setConfirmingApproval(true);
                  }}
                >
                  Approve final demand
                </Button>
              ) : null}
            </div>
          }
        />

        {demand.locked ? (
          <div className="border-b border-ok-200 bg-ok-50 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Badge tone="success" strong>
                Approved
              </Badge>
              <span className="text-body text-ink-body">
                by {demand.approved_by} on {formatDateTime(demand.approved_at)}
              </span>
              <span className="text-meta text-ink-muted">version {demand.version}</span>
            </div>
            <dl className="mt-2.5 grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="metric-label">DOCX SHA-256</dt>
                <dd className="mt-0.5 break-all font-mono text-2xs text-ink-muted">
                  {demand.docx_sha256 ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="metric-label">PDF SHA-256</dt>
                <dd className="mt-0.5 break-all font-mono text-2xs text-ink-muted">
                  {demand.pdf_sha256 ?? "Not generated"}
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-meta leading-5 text-ink-muted">
              These bytes are locked. Regeneration and section edits are refused by the backend
              from this point on.
            </p>
          </div>
        ) : null}

        {downloads.pdfUnavailable ? (
          <div className="border-b border-warn-200 bg-warn-50 px-4 py-2.5">
            <p className="text-meta text-warn-800">{downloads.pdfUnavailable}</p>
          </div>
        ) : null}

        {blockingCount > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stop-200 bg-stop-50 px-4 py-3">
            <p className="text-body text-stop-800">
              {blockingCount} blocking issue{blockingCount === 1 ? "" : "s"} must be resolved
              before this demand can be approved.
            </p>
            <Button size="sm" onClick={() => goToTab("validation")}>
              Review issues
            </Button>
          </div>
        ) : null}

        {demand.sections.length === 0 ? (
          <EmptyState
            title="Draft not generated"
            description="Generate the letter from the verified facts on file."
            action={
              <Button
                variant="primary"
                disabled={generate.isPending}
                onClick={() =>
                  generate.mutate(
                    { demandId: demand.id },
                    {
                      onSuccess: () => toast.push({ tone: "success", title: "Draft generated" }),
                      onError: (error) =>
                        toast.push({
                          tone: "error",
                          title: "Generation failed",
                          description: error.message,
                        }),
                    },
                  )
                }
              >
                {generate.isPending ? "Generating…" : "Generate draft"}
              </Button>
            }
          />
        ) : (
          <>
            {/* Section index — jump straight to the part under review. */}
            <div className="sticky top-0 z-10 flex flex-wrap gap-1 border-b border-line-soft bg-white/95 px-4 py-2 backdrop-blur">
              {demand.sections.map((section) => {
                const sectionBlocking = issuesFor(section.key).some(
                  (issue) => issue.severity === "BLOCKING",
                );
                const isSelected = focusedSection === section.key;
                return (
                  <button
                    key={section.id}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => selectSection(section.key)}
                    className={cn(
                      "rounded px-2 py-0.5 text-2xs font-medium transition-colors duration-150",
                      "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
                      isSelected
                        ? "bg-accent-700 text-white"
                        : sectionBlocking
                          ? "bg-stop-50 text-stop-700 hover:bg-stop-100"
                          : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                    )}
                  >
                    {section.title}
                  </button>
                );
              })}
            </div>

            {/* The letter itself, on a paper surface. */}
            <div className="bg-surface-sunken/40 px-4 py-5">
              <div className="mx-auto max-w-4xl divide-y divide-line-soft rounded border border-line bg-surface-paper shadow-paper">
                {demand.sections.map((section) => (
                  <SectionCard
                    key={section.id}
                    section={section}
                    issues={issuesFor(section.key)}
                    selected={focusedSection === section.key}
                    locked={demand.locked}
                    saving={editSection.isPending}
                    regenerating={generate.isPending}
                    onSelect={() => selectSection(section.key)}
                    onSave={(body) =>
                      editSection.mutate(
                        { demandId: demand.id, key: section.key, body },
                        {
                          onSuccess: () =>
                            toast.push({
                              tone: "success",
                              title: "Section saved",
                              description: "Re-run validation to check the edit.",
                            }),
                          onError: (error) =>
                            toast.push({
                              tone: "error",
                              title: "Could not save",
                              description: error.message,
                            }),
                        },
                      )
                    }
                    onRegenerate={() =>
                      generate.mutate(
                        { demandId: demand.id, regenerate_sections: [section.key] },
                        {
                          onSuccess: () =>
                            toast.push({
                              tone: "success",
                              title: `Regenerated ${section.title}`,
                            }),
                          onError: (error) =>
                            toast.push({
                              tone: "error",
                              title: "Regeneration failed",
                              description: error.message,
                            }),
                        },
                      )
                    }
                  />
                ))}
              </div>
              <p className="mx-auto mt-3 max-w-4xl text-2xs text-ink-faint">
                Select a section to see the verified facts and source evidence behind it in the
                context panel.
              </p>
            </div>
          </>
        )}
      </Panel>

      {focusedSection && !BLOCK_SECTIONS.has(focusedSection) ? (
        <RevisionPanel
          caseId={caseId}
          demandId={demand.id}
          sectionKey={focusedSection}
          sectionTitle={
            demand.sections.find((section) => section.key === focusedSection)?.title ??
            focusedSection
          }
          locked={demand.locked}
          canAccept={AUTH_USER_ROLE === "attorney" || AUTH_USER_ROLE === "admin"}
        />
      ) : null}

      <Modal
        open={confirmingApproval}
        onClose={() => setConfirmingApproval(false)}
        title="Approve final demand"
        description="You are approving the exact current demand version. The backend will re-run validation and lock/hash the approved bytes."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmingApproval(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={approve.isPending || acknowledgement.trim().length === 0}
              onClick={submitApproval}
            >
              {approve.isPending ? "Approving…" : "Approve and lock"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 rounded border border-line bg-surface-muted px-3 py-2.5">
            <div>
              <dt className="metric-label">Version</dt>
              <dd className="mt-0.5 text-body text-ink">{demand.version}</dd>
            </div>
            <div>
              <dt className="metric-label">Letter date</dt>
              <dd className="mt-0.5 text-body text-ink">{formatDate(demand.letter_date)}</dd>
            </div>
          </dl>

          <div>
            <label className="block text-meta font-medium text-ink-body" htmlFor="acknowledgement">
              Type the case reference{" "}
              <span className="font-mono text-meta text-ink">
                {caseQuery.data?.reference ?? ""}
              </span>{" "}
              to confirm you reviewed this draft
            </label>
            <input
              id="acknowledgement"
              value={acknowledgement}
              onChange={(event) => setAcknowledgement(event.target.value)}
              className="mt-1.5 w-full rounded border border-line-strong px-2.5 py-1.5 text-body"
              autoComplete="off"
            />
          </div>

          {approvalIssues.length > 0 ? (
            <div className="rounded border border-stop-200 bg-stop-50 px-3 py-2.5">
              <p className="text-meta font-semibold text-stop-800">
                The backend refused approval. Blocking issues remain:
              </p>
              <ul className="mt-1.5 space-y-1">
                {approvalIssues.map((issue) => (
                  <li key={`${issue.code}-${issue.section_key}`} className="text-meta text-stop-700">
                    <span className="font-mono font-semibold">{issue.code}</span>
                    {issue.section_key ? ` · ${humanize(issue.section_key)}` : ""} — {issue.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <Note>
            Approval is decided by the backend, not by this screen. Validation runs again at the
            moment of approval, so anything that changed since the last run is caught.
          </Note>
        </div>
      </Modal>
    </div>
  );
}
