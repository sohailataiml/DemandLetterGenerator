"use client";

/**
 * Section B of Documents: the evidence.
 *
 * Deliberately a separate card from the template with different words on it.
 * These two uploads have opposite trust roles — one supplies formatting and is
 * never read for facts, the other supplies facts and never touches formatting —
 * and a single "pick a document type" uploader would invite exactly the mistake
 * that matters most.
 */

import { useMemo, useState } from "react";

import { ApiError, apiDownload, saveBlob } from "@/lib/api/client";
import { useDeleteDocument, useDocuments, useFacts, useUploadLimits } from "@/lib/api/hooks";
import { formatBytes, formatDate, formatDateTime, humanize, shortHash } from "@/lib/format";
import {
  Badge,
  Button,
  ErrorState,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useEvidence } from "../evidence";
import { Dropzone } from "./dropzone";
import { UploadRow } from "./upload-row";
import { limitsForDocuments, useUploadQueue } from "./queue";
import type { BadgeTone } from "@/components/ui/primitives";
import type { Fact, SourceDocument } from "@/lib/api/types";

const STATUS_TONE: Record<string, BadgeTone> = {
  extracted: "success",
  needs_ocr: "warning",
  extraction_failed: "danger",
  stored: "muted",
};

const STATUS_LABEL: Record<string, string> = {
  extracted: "Ready",
  needs_ocr: "Needs OCR",
  extraction_failed: "Text unreadable",
  stored: "Stored",
};

/** Facts per document, so the list is useful after the uploading is done. */
function factCounts(facts: Fact[]): Map<string, { proposed: number; verified: number }> {
  const counts = new Map<string, { proposed: number; verified: number }>();
  for (const fact of facts) {
    const documentIds = new Set(fact.sources.map((source) => source.document_id));
    for (const documentId of documentIds) {
      const entry = counts.get(documentId) ?? { proposed: 0, verified: 0 };
      if (fact.status === "PROPOSED") entry.proposed += 1;
      if (fact.status === "VERIFIED") entry.verified += 1;
      counts.set(documentId, entry);
    }
  }
  return counts;
}

export function MaterialsCard({ caseId }: { caseId: string }) {
  const documentsQuery = useDocuments(caseId);
  const factsQuery = useFacts(caseId);
  const limitsQuery = useUploadLimits();
  const removeDocument = useDeleteDocument(caseId);
  const { show } = useEvidence();
  const toast = useToast();

  const [pendingRemoval, setPendingRemoval] = useState<SourceDocument | null>(null);
  const [removalError, setRemovalError] = useState<string | null>(null);

  const limits = limitsForDocuments(limitsQuery.data);
  const documents = documentsQuery.data ?? [];
  const counts = useMemo(() => factCounts(factsQuery.data ?? []), [factsQuery.data]);

  const queue = useUploadQueue({
    caseId,
    path: `/v1/cases/${caseId}/documents`,
    limits,
    duplicateCheck: (file) => {
      // A friendlier version of the 409 the server would return anyway. The
      // filename is a hint only — the server matches on content hash.
      const clash = documents.find((document) => document.original_filename === file.name);
      return clash ? `${file.name} is already on file for this case.` : null;
    },
  });

  const download = async (document: SourceDocument) => {
    try {
      const file = await apiDownload(`/v1/documents/${document.id}/content`);
      saveBlob(file.blob, file.filename || document.original_filename);
      toast.push({ tone: "success", title: "Original downloaded", description: file.filename });
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : String(caught);
      toast.push({ tone: "error", title: "Download failed", description: message });
    }
  };

  const confirmRemoval = () => {
    if (!pendingRemoval) return;
    setRemovalError(null);
    removeDocument.mutate(pendingRemoval.id, {
      onSuccess: () => {
        toast.push({
          tone: "success",
          title: "Document removed",
          description: pendingRemoval.original_filename,
        });
        setPendingRemoval(null);
      },
      onError: (error) => setRemovalError(error.message),
    });
  };

  const accept = (limits?.extensions ?? []).join(",");
  const formats = (limits?.extensions ?? [])
    .map((extension) => extension.replace(".", "").toUpperCase())
    .join(" · ");

  return (
    <>
      <Panel>
        <PanelHeader
          title="Case materials"
          description="Evidence used to prepare this demand. AI-extracted facts require attorney verification before they can be used in the letter."
          actions={
            documents.length > 0 ? (
              <Badge tone="neutral">{documents.length} on file</Badge>
            ) : (
              <Badge tone="warning" strong>
                Required
              </Badge>
            )
          }
        />

        <Dropzone
          id="materials-upload"
          label="Drop case documents here"
          hint={
            limits
              ? `${formats} · up to ${formatBytes(limits.maxBytes)} each`
              : "Medical records, bills, reports and other evidence"
          }
          buttonLabel="Choose documents"
          accept={accept}
          multiple
          busy={queue.busy}
          onFiles={queue.enqueue}
        />

        {queue.items.length > 0 ? (
          <ul className="divide-y divide-line-soft border-t border-line-soft">
            {queue.items.map((item) => (
              <UploadRow
                key={item.id}
                item={item}
                onRetry={queue.retry}
                onDismiss={queue.dismiss}
              />
            ))}
          </ul>
        ) : null}

        {documentsQuery.isLoading ? <SkeletonRows rows={3} /> : null}
        <ErrorState
          error={
            documentsQuery.error
              ? { message: documentsQuery.error.message, status: documentsQuery.error.status }
              : null
          }
          onRetry={() => documentsQuery.refetch()}
        />

        {documents.length > 0 ? (
          <ul className="divide-y divide-line-soft border-t border-line-soft">
            {documents.map((document) => {
              const facts = counts.get(document.id);
              const status = String(document.status).toLowerCase();
              return (
                <li key={document.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-body font-medium text-ink">
                      {document.original_filename}
                    </span>
                    <Badge tone="neutral">{humanize(document.document_type)}</Badge>
                    <Badge tone={STATUS_TONE[status] ?? "muted"} strong>
                      {STATUS_LABEL[status] ?? humanize(document.status)}
                    </Badge>
                  </div>

                  <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-faint">
                    <Meta label="Pages" value={String(document.page_count)} />
                    <Meta label="Size" value={formatBytes(document.size_bytes)} />
                    <Meta label="Provider" value={document.provider_name ?? "—"} />
                    <Meta label="Document date" value={formatDate(document.document_date)} />
                    <Meta
                      label="Uploaded"
                      value={`${formatDateTime(document.created_at)} by ${document.uploaded_by}`}
                    />
                    <Meta label="SHA-256" value={shortHash(document.sha256)} mono />
                  </dl>

                  {facts ? (
                    <p className="mt-1.5 text-meta text-ink-body">
                      {facts.verified} verified · {facts.proposed} awaiting review
                    </p>
                  ) : null}

                  {document.extraction_note ? (
                    <div className="mt-1.5">
                      <Note>{document.extraction_note}</Note>
                    </div>
                  ) : null}

                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => show({ kind: "document", documentId: document.id })}
                    >
                      View extracted text
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => download(document)}>
                      Download original
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRemovalError(null);
                        setPendingRemoval(document);
                      }}
                    >
                      Remove
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}

        {documents.length === 0 && !documentsQuery.isLoading && queue.items.length === 0 ? (
          <div className="border-t border-line-soft px-4 py-3">
            <Note>
              Nothing on file yet. A fact cannot be verified without a document to cite, so the
              evidence comes first.
            </Note>
          </div>
        ) : null}
      </Panel>

      <Modal
        open={Boolean(pendingRemoval)}
        onClose={() => setPendingRemoval(null)}
        title="Remove this document?"
        description="The stored original and its extracted text are deleted. This is recorded in the audit trail."
        footer={
          <>
            <Button variant="secondary" onClick={() => setPendingRemoval(null)}>
              Cancel
            </Button>
            <Button variant="danger" disabled={removeDocument.isPending} onClick={confirmRemoval}>
              {removeDocument.isPending ? "Removing…" : "Remove document"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-body text-ink">{pendingRemoval?.original_filename}</p>
          {removalError ? (
            <div role="alert" className="rounded border border-stop-200 bg-stop-50 px-3 py-2">
              <p className="text-meta text-stop-800">{removalError}</p>
            </div>
          ) : null}
          <Note>
            The server refuses to remove a document any fact cites — proposed, verified or
            rejected. Reject or supersede those facts first.
          </Note>
        </div>
      </Modal>
    </>
  );
}

function Meta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-1">
      <dt>{label}</dt>
      <dd className={`font-medium text-ink-body ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
