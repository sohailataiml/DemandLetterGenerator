"use client";

/**
 * Source evidence: click any fact or citation and see the document, page, and
 * the passage it came from. This is the provenance chain the whole system is
 * built to preserve, so it stays one click away from every screen.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { useDocument, useFacts } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FactStatusBadge,
  Field,
  Note,
  SectionHeading,
  Skeleton,
} from "@/components/ui/primitives";
import { CitationStatusBadge, SourceViewer, citationStatusOf } from "./source-viewer";
import type { Fact, FactSource } from "@/lib/api/types";

export type EvidenceSelection =
  | { kind: "fact"; factId: string }
  | {
      kind: "document";
      documentId: string;
      page?: number | null;
      excerpt?: string | null;
      span?: CitationSpan | null;
    }
  | null;

interface EvidenceContextValue {
  selection: EvidenceSelection;
  show: (selection: EvidenceSelection) => void;
  clear: () => void;
}

const EvidenceContext = createContext<EvidenceContextValue | null>(null);

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<EvidenceSelection>(null);
  const show = useCallback((next: EvidenceSelection) => setSelection(next), []);
  const clear = useCallback(() => setSelection(null), []);
  const value = useMemo(() => ({ selection, show, clear }), [selection, show, clear]);
  return <EvidenceContext.Provider value={value}>{children}</EvidenceContext.Provider>;
}

export function useEvidence(): EvidenceContextValue {
  return (
    useContext(EvidenceContext) ?? {
      selection: null,
      show: () => undefined,
      clear: () => undefined,
    }
  );
}

export interface CitationSpan {
  start_offset: number | null;
  end_offset: number | null;
  match_kind: "exact" | "normalized" | "approximate" | null;
}

/**
 * Highlight the cited passage inside the page text.
 *
 * The backend records character offsets when it could locate the quote in the
 * stored page, so the first choice is to use them — no searching, no guessing.
 * Searching for the excerpt is the fallback for older citations that have no
 * offsets, and an approximate match is labelled as approximate rather than
 * presented as if it were exact.
 */
function HighlightedText({
  text,
  excerpt,
  span,
}: {
  text: string;
  excerpt?: string | null;
  span?: CitationSpan | null;
}) {
  if (!excerpt && !span?.start_offset) {
    return <p className="whitespace-pre-wrap text-meta leading-6 text-ink-body">{text}</p>;
  }

  const hasOffsets =
    span != null &&
    span.start_offset != null &&
    span.end_offset != null &&
    span.start_offset >= 0 &&
    span.end_offset <= text.length &&
    span.end_offset > span.start_offset;

  const start = hasOffsets
    ? (span!.start_offset as number)
    : excerpt
      ? text.toLowerCase().indexOf(excerpt.trim().toLowerCase())
      : -1;
  const end = hasOffsets
    ? (span!.end_offset as number)
    : start >= 0 && excerpt
      ? start + excerpt.trim().length
      : -1;

  if (start < 0 || end <= start) {
    return (
      <>
        <div className="rounded border border-warn-200 bg-warn-50 px-2 py-1.5">
          <p className="text-2xs font-medium uppercase tracking-[0.06em] text-warn-800">
            Cited passage
          </p>
          <p className="mt-0.5 text-meta italic leading-5 text-warn-800">{excerpt}</p>
          <p className="mt-1 text-2xs text-warn-700">
            Not found verbatim on this page — the citation may be a paraphrase.
          </p>
        </div>
        <p className="mt-2 whitespace-pre-wrap text-meta leading-6 text-ink-body">{text}</p>
      </>
    );
  }

  const approximate = span?.match_kind === "approximate" || !hasOffsets;

  return (
    <>
      <p className="whitespace-pre-wrap text-meta leading-6 text-ink-body">
        {text.slice(0, start)}
        <mark
          data-testid="citation-highlight"
          data-match-kind={span?.match_kind ?? "search"}
          className={cn(
            "rounded px-0.5 text-ink",
            approximate ? "bg-warn-100" : "bg-ok-100 ring-1 ring-inset ring-ok-200",
          )}
        >
          {text.slice(start, end)}
        </mark>
        {text.slice(end)}
      </p>
      <p className="mt-1 text-2xs text-ink-faint">
        {approximate
          ? "Approximate match — this highlight is the closest passage, not an exact citation."
          : "Exact citation — these are the recorded character offsets in this page."}
      </p>
    </>
  );
}

/**
 * What the rail says about a citation's precision.
 *
 * Four states, four sentences. Collapsing any two of them would let the rail
 * imply a level of certainty the citation does not carry — which is the one
 * thing this panel must never do.
 */
function railCitationNote(citation: FactSource): string {
  switch (citationStatusOf(citation)) {
    case "EXACT":
      return citation.bounding_boxes?.length
        ? "Exact source match — the passage is highlighted on the original page."
        : "Exact source match in the page text. This source has no page layout, so no region can be highlighted.";
    case "AMBIGUOUS":
      return "Multiple matching passages found. Select the supporting passage in the source viewer.";
    case "TEXT_ONLY":
      return "Citation available at page level only. Exact highlight unavailable.";
    default:
      return "No passage recorded for this citation. The supporting page is shown instead.";
  }
}

function DocumentEvidence({
  caseId,
  documentId,
  page,
  excerpt,
  span,
  citation,
}: {
  caseId: string;
  documentId: string;
  page?: number | null;
  excerpt?: string | null;
  span?: CitationSpan | null;
  citation?: FactSource | null;
}) {
  const { data, isLoading, error } = useDocument(documentId);
  const [viewerPage, setViewerPage] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (error) return <ErrorState error={{ message: error.message, status: error.status }} />;
  if (!data) return null;

  const pages = page ? data.pages.filter((item) => item.page_number === page) : data.pages;

  return (
    <div className="space-y-3 p-4">
      {/* Where this came from, said first and plainly. */}
      <div className="rounded border border-line bg-surface-muted px-3 py-2.5">
        <p className="text-body font-semibold text-ink">{data.provider_name ?? data.original_filename}</p>
        <p className="mt-0.5 text-meta text-ink-muted">
          {formatDate(data.document_date)}
          {page ? (
            <>
              <span className="px-1.5 text-ink-faint">·</span>Page {page}
            </>
          ) : null}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Badge tone="neutral">{humanize(data.document_type)}</Badge>
          <Badge tone="muted">{data.page_count} pages</Badge>
          {citation ? <CitationStatusBadge citation={citation} /> : null}
        </div>
        {citation ? (
          <div className="mt-2">
            {citation.excerpt ? (
              <>
                <p className="eyebrow">Quoted evidence</p>
                <blockquote
                  data-testid="quoted-evidence"
                  className="mt-0.5 border-l-2 border-line-strong pl-2 text-meta italic leading-5 text-ink-body"
                >
                  {citation.excerpt}
                </blockquote>
              </>
            ) : null}
            <p className="mt-1 text-2xs leading-4 text-ink-faint" data-testid="rail-citation-note">
              {railCitationNote(citation)}
            </p>
          </div>
        ) : null}
        {/* The one click from a citation to the evidence itself. */}
        <Button
          size="sm"
          variant="secondary"
          className="mt-2"
          onClick={() => setViewerPage(page ?? 1)}
        >
          {citation && citationStatusOf(citation) === "EXACT" && citation.bounding_boxes?.length
            ? "Open highlighted source"
            : "Open original source"}
        </Button>
      </div>

      {data.extraction_note ? (
        <div className="rounded border border-line bg-surface-muted px-2.5 py-2">
          <Note>{data.extraction_note}</Note>
        </div>
      ) : null}

      <div>
        <SectionHeading>Extracted text{page ? ` — page ${page}` : ""}</SectionHeading>
        <p className="mt-1 text-2xs leading-4 text-ink-faint">
          Extracted text, not the original file. Download the original from the Documents tab.
        </p>
        <div className="mt-2 space-y-3">
          {pages.map((item) => (
            <div key={item.page_number} className="rounded border border-line bg-white p-2.5">
              <p className="mb-1 text-2xs font-medium uppercase tracking-[0.06em] text-ink-faint">
                Page {item.page_number}
              </p>
              {item.text ? (
                <HighlightedText text={item.text} excerpt={excerpt} span={span} />
              ) : (
                <Note>No extractable text on this page.</Note>
              )}
            </div>
          ))}
        </div>
      </div>

      <details className="rounded border border-line">
        <summary className="cursor-pointer px-2.5 py-1.5 text-2xs text-ink-muted">
          Document integrity
        </summary>
        <dl className="space-y-1.5 border-t border-line-soft px-2.5 py-2">
          <Field label="Filename">
            <span className="text-meta">{data.original_filename}</span>
          </Field>
          <Field label="SHA-256">
            <span className="break-all font-mono text-2xs text-ink-muted">{data.sha256}</span>
          </Field>
        </dl>
      </details>

      {viewerPage != null ? (
        <SourceViewer
          caseId={caseId}
          documentId={documentId}
          pageNumber={viewerPage}
          citation={citation}
          onClose={() => setViewerPage(null)}
        />
      ) : null}
    </div>
  );
}

function FactEvidence({ caseId, factId }: { caseId: string; factId: string }) {
  const { data, isLoading, error } = useFacts(caseId);
  const [activeSource, setActiveSource] = useState<FactSource | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (error) return <ErrorState error={{ message: error.message, status: error.status }} />;

  const fact: Fact | undefined = data?.find((item) => item.id === factId);
  if (!fact) {
    return <EmptyState title="Fact not found" description="It may have been superseded." />;
  }

  const source = activeSource ?? fact.sources[0] ?? null;

  return (
    <div className="space-y-3 p-4">
      <div>
        <SectionHeading>Fact</SectionHeading>
        <div className="mt-1.5 rounded border border-line bg-white px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <FactStatusBadge status={fact.status} />
            <Badge tone="neutral">{humanize(fact.fact_type)}</Badge>
            {fact.revision > 1 ? <Badge tone="muted">rev {fact.revision}</Badge> : null}
          </div>
          <p className="mt-2 text-body leading-6 text-ink-body">{fact.summary}</p>
          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-faint">
            <div className="flex gap-1">
              <dt>Proposed by</dt>
              <dd className="font-medium text-ink-muted">{fact.proposed_by}</dd>
            </div>
            <div className="flex gap-1">
              <dt>Verified by</dt>
              <dd className="font-medium text-ink-muted">{fact.reviewed_by ?? "—"}</dd>
            </div>
          </dl>
        </div>
      </div>

      <p className="text-center text-2xs text-ink-faint" aria-hidden>
        ↓ supported by
      </p>

      {fact.sources.length > 1 ? (
        <div>
          <SectionHeading>Citations</SectionHeading>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {fact.sources.map((item) => (
              <Button
                key={item.id}
                size="sm"
                variant={source?.id === item.id ? "primary" : "secondary"}
                onClick={() => setActiveSource(item)}
              >
                Page {item.page_number ?? "—"}
              </Button>
            ))}
          </div>
        </div>
      ) : null}

      {source ? (
        <div className="-mx-4 border-t border-line">
          <DocumentEvidence
            caseId={caseId}
            documentId={source.document_id}
            page={source.page_number}
            excerpt={source.excerpt}
            span={source}
            citation={{ ...source, fact_id: source.fact_id ?? fact.id }}
          />
        </div>
      ) : (
        <Note>This fact has no source citation on file.</Note>
      )}
    </div>
  );
}

export function EvidencePanel({ caseId }: { caseId: string }) {
  const { selection, clear } = useEvidence();
  if (!selection) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="text-body font-semibold text-ink">Source evidence</h2>
        <Button size="sm" variant="ghost" onClick={clear} aria-label="Close evidence panel">
          Close
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {selection.kind === "fact" ? (
          <FactEvidence caseId={caseId} factId={selection.factId} />
        ) : (
          <DocumentEvidence
            caseId={caseId}
            documentId={selection.documentId}
            page={selection.page}
            excerpt={selection.excerpt}
            span={selection.span}
          />
        )}
      </div>
    </div>
  );
}
