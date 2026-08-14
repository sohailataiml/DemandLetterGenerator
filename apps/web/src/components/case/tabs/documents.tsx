"use client";

/**
 * Documents: where a case actually starts.
 *
 * Two uploads with opposite trust roles, kept visually and structurally apart:
 * the template controls how the letter looks and is never read for facts; the
 * case materials supply the facts and never touch the formatting. Below them,
 * the one action that turns evidence into reviewable facts.
 */

import { useDemands, useDocuments, useFacts, useTemplates } from "@/lib/api/hooks";
import { Note, Panel, PanelHeader } from "@/components/ui/primitives";
import { CaseSetup } from "../upload/case-setup";
import { ExtractionPanel } from "../upload/extraction";
import { MaterialsCard } from "../upload/materials-card";
import { TemplateCard } from "../upload/template-card";
import type { TabProps } from "../workspace";

export function DocumentsTab({ caseId, goToTab }: TabProps) {
  const templatesQuery = useTemplates(caseId);
  const documentsQuery = useDocuments(caseId);
  const factsQuery = useFacts(caseId);
  const demandsQuery = useDemands(caseId);

  const templates = templatesQuery.data ?? [];
  const documents = documentsQuery.data ?? [];
  const facts = factsQuery.data ?? [];
  const demand = demandsQuery.data?.[0] ?? null;

  const settled = !templatesQuery.isLoading && !documentsQuery.isLoading;
  const firstRun = settled && templates.length === 0 && documents.length === 0;

  return (
    <div className="space-y-4">
      {!firstRun ? (
        <CaseSetup
          templates={templates}
          documents={documents}
          facts={facts}
          demand={demand}
        />
      ) : (
        <Panel>
          <PanelHeader
            title="Start here"
            description="Add the attorney's demand template and the evidence for this case."
          />
          <ol className="divide-y divide-line-soft">
            <Step
              number={1}
              title="Demand template"
              body="Upload the Word document whose formatting should be preserved. The finished letter is written into a copy of it."
            />
            <Step
              number={2}
              title="Case materials"
              body="Upload medical records, bills, reports and other evidence. Extraction reads these; it cannot propose a fact without a passage to cite."
            />
            <Step
              number={3}
              title="Verify facts"
              body="AI-extracted facts arrive as proposals. An attorney verifies each one before it can appear in the demand."
              waiting
            />
          </ol>
        </Panel>
      )}

      <TemplateCard caseId={caseId} />
      <MaterialsCard caseId={caseId} />
      <ExtractionPanel caseId={caseId} goToTab={goToTab} />

      <Panel>
        <PanelHeader title="How these files are treated" dense />
        <div className="grid gap-4 px-4 py-3 sm:grid-cols-2">
          <div>
            <p className="eyebrow">Template</p>
            <p className="mt-1 text-meta leading-6 text-ink-muted">
              Controls structure and formatting. Read as a Word document and nothing else — no
              macros run, no embedded content is executed, and no sentence in it becomes a fact.
            </p>
          </div>
          <div>
            <p className="eyebrow">Case materials</p>
            <p className="mt-1 text-meta leading-6 text-ink-muted">
              Provide evidence. Their text is untrusted data, never an instruction: an extractor
              cannot verify its own output, cannot cite a passage that is not in the file, and
              cannot put a number in the letter.
            </p>
          </div>
        </div>
        <div className="border-t border-line-soft px-4 py-2.5">
          <Note>
            Uploads are screened for type, size and known malware signatures, and stored under a
            content hash rather than the name they arrived with.
          </Note>
        </div>
      </Panel>
    </div>
  );
}

function Step({
  number,
  title,
  body,
  waiting = false,
}: {
  number: number;
  title: string;
  body: string;
  waiting?: boolean;
}) {
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-2xs font-semibold text-ink-muted">
        {number}
      </span>
      <div className="min-w-0">
        <p className="text-body font-medium text-ink">{title}</p>
        <p className="mt-0.5 text-meta leading-6 text-ink-muted">{body}</p>
        {waiting ? (
          <p className="mt-1 text-2xs uppercase tracking-[0.07em] text-ink-faint">
            Waiting for documents
          </p>
        ) : null}
      </div>
    </li>
  );
}
