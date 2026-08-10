"use client";

import { useDocuments } from "@/lib/api/hooks";
import { API_BASE_URL, ApiError, apiDownload, saveBlob } from "@/lib/api/client";
import { formatBytes, formatDate, formatDateTime, humanize, shortHash } from "@/lib/format";
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
import { useToast } from "@/components/ui/toast";
import { useEvidence } from "../evidence";
import type { TabProps } from "../workspace";

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "muted"> = {
  extracted: "success",
  needs_ocr: "warning",
  extraction_failed: "danger",
  stored: "muted",
};

export function DocumentsTab({ caseId }: TabProps) {
  const { data, isLoading, error, refetch } = useDocuments(caseId);
  const { show } = useEvidence();
  const toast = useToast();

  const download = async (documentId: string, filename: string) => {
    try {
      const file = await apiDownload(`/v1/documents/${documentId}/content`);
      saveBlob(file.blob, file.filename || filename);
      toast.push({ tone: "success", title: "Original downloaded", description: file.filename });
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : String(caught);
      toast.push({ tone: "error", title: "Download failed", description: message });
    }
  };

  return (
    <Panel>
      <PanelHeader
        title="Source documents"
        description="Originals are content-addressed and immutable. Extracted text is a separate, derived view."
        actions={<span className="text-2xs text-ink-faint">{API_BASE_URL}</span>}
      />

      {isLoading ? <SkeletonRows rows={4} /> : null}
      <ErrorState
        error={error ? { message: error.message, status: error.status } : null}
        onRetry={() => refetch()}
      />
      {data && data.length === 0 ? (
        <EmptyState
          title="No documents uploaded"
          description="Facts cannot be verified without a source document to cite."
        />
      ) : null}

      {data && data.length > 0 ? (
        <ul className="divide-y divide-line-soft">
          {data.map((document) => (
            <li key={document.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-body font-medium text-ink">
                  {document.original_filename}
                </span>
                <Badge tone="neutral">{humanize(document.document_type)}</Badge>
                <Badge tone={STATUS_TONE[document.status] ?? "muted"}>
                  {humanize(document.status)}
                </Badge>
              </div>

              <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-faint">
                <div className="flex gap-1">
                  <dt>Provider</dt>
                  <dd className="font-medium text-ink-body">{document.provider_name ?? "—"}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>Document date</dt>
                  <dd className="font-medium text-ink-body">
                    {formatDate(document.document_date)}
                  </dd>
                </div>
                <div className="flex gap-1">
                  <dt>Pages</dt>
                  <dd className="font-medium text-ink-body">{document.page_count}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>Size</dt>
                  <dd className="font-medium text-ink-body">{formatBytes(document.size_bytes)}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>Uploaded</dt>
                  <dd className="font-medium text-ink-body">
                    {formatDateTime(document.created_at)} by {document.uploaded_by}
                  </dd>
                </div>
                <div className="flex gap-1">
                  <dt>SHA-256</dt>
                  <dd className="font-mono font-medium text-ink-body" title={document.sha256}>
                    {shortHash(document.sha256)}
                  </dd>
                </div>
              </dl>

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
                  Review extracted text
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => download(document.id, document.original_filename)}
                >
                  Download original
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
