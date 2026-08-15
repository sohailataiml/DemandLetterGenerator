"use client";

/**
 * The original source, on the exact page, with the exact passage highlighted.
 *
 * This is the end of the provenance chain and the only screen in the product
 * that shows the evidence itself rather than a rendering of what the system
 * extracted from it. Two rules govern everything here:
 *
 * 1. **The highlight may never be more confident than the citation.** Only an
 *    EXACT citation with stored rectangles gets a geometric highlight. A
 *    paraphrase gets the page and a plain statement that no exact region is
 *    known; an ambiguous quote gets a chooser, not a guess.
 * 2. **The original is never altered.** The PDF is rendered as-is and the
 *    highlight is a translucent layer over it, positioned in the normalized
 *    coordinates the backend recorded.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useDocument, useDocumentPage, usePageGeometry, useResolveCitation } from "@/lib/api/hooks";
import { boxesForSpan, contextAround, findOccurrences } from "@/lib/provenance";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { Badge, Button, ErrorState, Note, Skeleton } from "@/components/ui/primitives";
import { PdfPage, type PdfPageState } from "./pdf-page";
import type { BoundingBox, CitationStatus, FactSource } from "@/lib/api/types";

const PDF_MIME = "application/pdf";

const STATUS_LABEL: Record<CitationStatus, string> = {
  EXACT: "Exact source match",
  AMBIGUOUS: "Multiple matching passages",
  TEXT_ONLY: "Page-level citation",
  UNRESOLVED: "No passage recorded",
};

const STATUS_TONE = {
  EXACT: "success",
  AMBIGUOUS: "warning",
  TEXT_ONLY: "warning",
  UNRESOLVED: "muted",
} as const;

export function citationStatusOf(citation: FactSource | null | undefined): CitationStatus {
  if (!citation) return "UNRESOLVED";
  if (citation.citation_status) return citation.citation_status;
  // Citations written before provenance had a status column: infer the same
  // grades from what they do record, never anything stronger.
  if (citation.match_kind === "exact" || citation.match_kind === "normalized") return "EXACT";
  if (citation.match_kind === "approximate") return "TEXT_ONLY";
  return "UNRESOLVED";
}

export function CitationStatusBadge({ citation }: { citation: FactSource | null | undefined }) {
  const status = citationStatusOf(citation);
  const geometric = status === "EXACT" && Boolean(citation?.bounding_boxes?.length);
  return (
    <span data-testid="citation-status">
      <Badge tone={STATUS_TONE[status]} strong>
        {geometric ? "Exact source match" : STATUS_LABEL[status]}
      </Badge>
    </span>
  );
}

/** Translucent rectangles over the rendered page, in normalized coordinates. */
export function HighlightOverlay({
  boxes,
  tone = "exact",
  label,
  scrollIntoView = false,
}: {
  boxes: BoundingBox[];
  tone?: "exact" | "candidate";
  label?: string;
  /** Bring the first rectangle into view — the reviewer should not hunt. */
  scrollIntoView?: boolean;
}) {
  const first = useRef<HTMLDivElement>(null);
  const key = boxes.length > 0 ? `${boxes[0].x}-${boxes[0].y}` : "";
  useEffect(() => {
    if (!scrollIntoView || !key) return;
    first.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [scrollIntoView, key]);

  if (boxes.length === 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {boxes.map((box, index) => (
        <div
          key={`${box.x}-${box.y}-${index}`}
          ref={index === 0 ? first : undefined}
          data-testid="citation-box"
          data-tone={tone}
          title={label}
          className={cn(
            "absolute rounded-[2px] mix-blend-multiply",
            tone === "exact"
              ? "bg-warn-200/60 ring-1 ring-warn-500"
              : "bg-accent-100/50 ring-1 ring-accent-400",
          )}
          style={{
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.width * 100}%`,
            height: `${box.height * 100}%`,
          }}
        />
      ))}
    </div>
  );
}

/** The page text with the cited span marked — the fallback, and the picker. */
function PageText({
  text,
  span,
  exact,
}: {
  text: string;
  span: { start: number; end: number } | null;
  exact: boolean;
}) {
  if (!span) {
    return <p className="whitespace-pre-wrap text-meta leading-6 text-ink-body">{text}</p>;
  }
  return (
    <p className="whitespace-pre-wrap text-meta leading-6 text-ink-body">
      {text.slice(0, span.start)}
      <mark
        data-testid="page-text-highlight"
        className={cn(
          "rounded px-0.5 text-ink",
          exact ? "bg-warn-200 ring-1 ring-inset ring-warn-400" : "bg-warn-100",
        )}
      >
        {text.slice(span.start, span.end)}
      </mark>
      {text.slice(span.end)}
    </p>
  );
}

/** What the viewer tells the reviewer about how far the evidence goes. */
function honestyNote(status: CitationStatus, hasBoxes: boolean): string {
  switch (status) {
    case "EXACT":
      return hasBoxes
        ? "This passage was located verbatim on this page; the highlight is the recorded region."
        : "This passage was located verbatim in the page text. The source has no page layout, so no region can be highlighted.";
    case "TEXT_ONLY":
      return "Exact source highlight unavailable — the quote is a paraphrase. The supporting page is shown instead.";
    case "AMBIGUOUS":
      return "This passage appears more than once on this page. Select the one that supports the fact.";
    default:
      return "No passage is recorded for this citation. The supporting page is shown instead.";
  }
}

export interface SourceViewerProps {
  documentId: string;
  pageNumber: number;
  citation?: FactSource | null;
  caseId: string;
  onClose: () => void;
  /** Injectable page renderer. Tests pass a stub instead of running PDF.js. */
  renderPage?: (props: {
    documentId: string;
    pageNumber: number;
    onStateChange: (state: PdfPageState, detail?: string) => void;
  }) => ReactNode;
}

/**
 * A dialog, not a route: opening evidence must never lose the reviewer's place
 * in the demand they were reading.
 */
export function SourceViewer({
  documentId,
  pageNumber,
  citation,
  caseId,
  onClose,
  renderPage,
}: SourceViewerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(pageNumber);
  const [renderState, setRenderState] = useState<PdfPageState>("loading");
  const [selected, setSelected] = useState<{ start: number; end: number } | null>(null);

  const document = useDocument(documentId);
  const pageQuery = useDocumentPage(documentId, page);
  const status = citationStatusOf(citation);
  const onCitationPage = citation?.page_number === page;

  // Geometry is only worth fetching when there is a passage to place on this
  // page and the page says it has any: this is the lazy half of the contract.
  const wantsGeometry = status === "AMBIGUOUS" && onCitationPage;
  const geometry = usePageGeometry(
    documentId,
    page,
    wantsGeometry && Boolean(pageQuery.data?.has_geometry),
  );

  const resolve = useResolveCitation(caseId);

  useEffect(() => setPage(pageNumber), [pageNumber]);
  useEffect(() => setSelected(null), [page]);

  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
    };
    window.document.addEventListener("keydown", onKeyDown);
    panelRef.current?.focus();
    return () => window.document.removeEventListener("keydown", onKeyDown);
  }, []);

  const pageText = pageQuery.data?.text ?? "";
  const occurrences = useMemo(
    () =>
      status === "AMBIGUOUS" && citation?.excerpt
        ? findOccurrences(pageText, citation.excerpt)
        : [],
    [status, citation?.excerpt, pageText],
  );

  const storedBoxes = onCitationPage ? (citation?.bounding_boxes ?? []) : [];
  const previewBoxes = useMemo(() => {
    if (!selected || !geometry.data?.words?.length) return [];
    return boxesForSpan(geometry.data.words, selected);
  }, [selected, geometry.data]);

  const citedSpan =
    onCitationPage &&
    citation?.start_offset != null &&
    citation?.end_offset != null &&
    citation.end_offset <= pageText.length
      ? { start: citation.start_offset, end: citation.end_offset }
      : null;

  const isPdf = document.data?.mime_type === PDF_MIME;
  const showsOriginal = isPdf && renderState !== "unavailable";
  const pageCount = document.data?.page_count ?? 1;

  const onResolve = useCallback(() => {
    if (!selected || !citation?.fact_id) return;
    resolve.mutate(
      {
        citationId: citation.id,
        factId: citation.fact_id,
        start_offset: selected.start,
        end_offset: selected.end,
      },
      { onSuccess: () => setSelected(null) },
    );
  }, [citation?.fact_id, citation?.id, resolve, selected]);

  const title = document.data?.provider_name ?? document.data?.original_filename ?? "Source";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Original source — ${title}, page ${page}`}
        tabIndex={-1}
        className="relative z-10 flex max-h-[92vh] w-full max-w-5xl flex-col rounded-md border border-line bg-white shadow-lg outline-none"
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <p className="eyebrow">Original source</p>
            <h2 className="mt-0.5 truncate card-title">{title}</h2>
            <p className="mt-0.5 text-2xs text-ink-faint">
              {document.data?.original_filename}
              {document.data?.document_date ? ` · ${formatDate(document.data.document_date)}` : ""}
              {` · Page ${page} of ${pageCount}`}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <CitationStatusBadge citation={citation} />
            <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close source viewer">
              Close
            </Button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3 lg:flex-row">
          <div className="min-w-0 flex-1">
            {document.error ? (
              <ErrorState
                error={{ message: document.error.message, status: document.error.status }}
              />
            ) : showsOriginal ? (
              <div className="relative mx-auto w-full max-w-3xl border border-line shadow-sm">
                {renderPage ? (
                  renderPage({
                    documentId,
                    pageNumber: page,
                    onStateChange: (next) => setRenderState(next),
                  })
                ) : (
                  <PdfPage
                    documentId={documentId}
                    pageNumber={page}
                    onStateChange={(next) => setRenderState(next)}
                  />
                )}
                {/* Rule 1 in the header comment, enforced in one place. */}
                {status === "EXACT" && storedBoxes.length > 0 ? (
                  <HighlightOverlay
                    boxes={storedBoxes}
                    label={citation?.excerpt ?? undefined}
                    scrollIntoView={renderState === "ready"}
                  />
                ) : null}
                {previewBoxes.length > 0 ? (
                  <HighlightOverlay boxes={previewBoxes} tone="candidate" />
                ) : null}
                {renderState === "loading" ? (
                  <Skeleton className="absolute inset-0 h-full w-full" />
                ) : null}
              </div>
            ) : (
              <div className="rounded border border-line bg-white p-3">
                <p className="mb-2 text-2xs text-ink-faint">
                  {isPdf
                    ? "The original page could not be rendered here. The extracted text of this page is shown instead."
                    : "This source has no page image to render. The extracted text of this page is shown instead."}
                </p>
                {pageQuery.isLoading ? (
                  <Skeleton className="h-64 w-full" />
                ) : (
                  <PageText
                    text={pageText}
                    span={citedSpan}
                    exact={status === "EXACT"}
                  />
                )}
              </div>
            )}
          </div>

          <aside className="w-full shrink-0 space-y-3 lg:w-80">
            <div className="rounded border border-line bg-surface-muted px-3 py-2.5">
              <p className="eyebrow">Citation</p>
              {citation?.excerpt ? (
                <blockquote className="mt-1 border-l-2 border-line-strong pl-2 text-meta italic leading-5 text-ink-body">
                  {citation.excerpt}
                </blockquote>
              ) : (
                <Note>This citation names a page, not a passage.</Note>
              )}
              <p className="mt-2 text-2xs leading-4 text-ink-faint" data-testid="citation-honesty">
                {honestyNote(status, storedBoxes.length > 0)}
              </p>
            </div>

            {status === "AMBIGUOUS" ? (
              <div className="rounded border border-warn-200 bg-warn-50 px-3 py-2.5">
                <p className="text-2xs font-medium uppercase tracking-[0.06em] text-warn-800">
                  Select supporting passage
                </p>
                {occurrences.length === 0 ? (
                  <Note>
                    The passage could not be located on this page for selection. Open the page and
                    supersede the fact if the citation is wrong.
                  </Note>
                ) : (
                  <ul className="mt-1.5 space-y-1.5">
                    {occurrences.map((span, index) => (
                      <li key={`${span.start}-${span.end}`}>
                        <button
                          type="button"
                          onClick={() => setSelected(span)}
                          aria-pressed={selected?.start === span.start}
                          className={cn(
                            "w-full rounded border px-2 py-1.5 text-left text-2xs leading-4",
                            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
                            selected?.start === span.start
                              ? "border-accent-400 bg-white text-ink"
                              : "border-line bg-white/60 text-ink-muted hover:bg-white",
                          )}
                        >
                          <span className="font-medium">Occurrence {index + 1}</span>
                          <span className="mt-0.5 block">{contextAround(pageText, span)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <Button
                  size="sm"
                  variant="primary"
                  className="mt-2"
                  disabled={!selected || !citation?.fact_id || resolve.isPending}
                  onClick={onResolve}
                >
                  {resolve.isPending ? "Saving…" : "Use this passage"}
                </Button>
                {resolve.error ? (
                  <p className="mt-1 text-2xs text-stop-700">{resolve.error.message}</p>
                ) : null}
              </div>
            ) : null}

            <div className="flex items-center justify-between gap-2">
              <Button
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous page
              </Button>
              <Button
                size="sm"
                disabled={page >= pageCount}
                onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              >
                Next page
              </Button>
            </div>
            {!onCitationPage ? (
              <Note>
                Showing page {page}. The citation is on page {citation?.page_number ?? "—"}.
              </Note>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}
