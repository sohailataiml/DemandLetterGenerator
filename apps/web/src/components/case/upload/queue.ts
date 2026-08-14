"use client";

/**
 * The client side of an upload, as a state machine.
 *
 * Each state corresponds to something that actually happens rather than to a
 * spinner someone wanted on screen:
 *
 *   SELECTED    chosen in the browser, nothing sent yet
 *   UPLOADING   bytes on the wire — the percentage is XHR's, not a guess
 *   PROCESSING  last byte delivered, waiting on the server. This is the window
 *               in which ingestion scans the file, extracts its text and
 *               paginates it, because that work happens inside the POST
 *   UPLOADED    stored, but its text could not be read (a scanned PDF needs
 *               OCR) — on file, not yet usable as evidence
 *   READY       stored and readable, so extraction can cite it
 *   FAILED      refused or unreachable, with the server's own reason
 *
 * Validation here is a courtesy that saves a doomed round trip. The limits come
 * from `/v1/upload-limits`, and the server re-checks every byte regardless.
 */

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, apiUpload } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/hooks";
import type { SourceDocument, UploadLimits } from "@/lib/api/types";

export type UploadState =
  | "SELECTED"
  | "UPLOADING"
  | "PROCESSING"
  | "UPLOADED"
  | "READY"
  | "FAILED";

export interface UploadItem {
  id: string;
  file: File;
  name: string;
  size: number;
  state: UploadState;
  /** null while the browser cannot compute a total. */
  percent: number | null;
  error: string | null;
  /** Kept so a 409 duplicate can read differently from a 400 rejection. */
  errorStatus: number | null;
  /**
   * Whether sending the same bytes again could plausibly succeed. False for a
   * file this browser rejected and for a duplicate already on file: offering
   * "Retry" there promises a different outcome that cannot happen.
   */
  retryable: boolean;
  documentId: string | null;
}

/** Document statuses that mean the text is usable for extraction. */
const READABLE = new Set(["extracted", "EXTRACTED"]);

export interface ValidationLimits {
  maxBytes: number;
  extensions: string[];
}

export function limitsForDocuments(limits: UploadLimits | undefined): ValidationLimits | null {
  if (!limits) return null;
  return { maxBytes: limits.max_upload_bytes, extensions: limits.allowed_extensions };
}

export function limitsForTemplate(limits: UploadLimits | undefined): ValidationLimits | null {
  if (!limits) return null;
  return { maxBytes: limits.max_template_bytes, extensions: limits.template_extensions };
}

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/**
 * Reject what the server would reject anyway, in the words an attorney needs.
 * Returns null when the file looks acceptable — which is a prediction, not a
 * permission.
 */
export function validateFile(file: File, limits: ValidationLimits | null): string | null {
  if (!limits) return null;
  const extension = extensionOf(file.name);
  if (!limits.extensions.includes(extension)) {
    return `${extension || "This file type"} is not accepted. Allowed: ${limits.extensions.join(", ")}.`;
  }
  if (file.size > limits.maxBytes) {
    return `File is ${formatMegabytes(file.size)}; the limit is ${formatMegabytes(limits.maxBytes)}.`;
  }
  if (file.size === 0) return "File is empty.";
  return null;
}

function formatMegabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

let counter = 0;
function nextId(): string {
  counter += 1;
  return `upload-${counter}`;
}

export interface UseUploadQueueOptions {
  caseId: string;
  path: string;
  limits: ValidationLimits | null;
  /** Reject a file before it is queued — used to block re-uploading a name. */
  duplicateCheck?: (file: File) => string | null;
  onUploaded?: (document: SourceDocument) => void;
}

export function useUploadQueue({
  caseId,
  path,
  limits,
  duplicateCheck,
  onUploaded,
}: UseUploadQueueOptions) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const queryClient = useQueryClient();
  // Kept in a ref so a send started before a re-render still writes to the
  // right item, and so `retry` can find the original File.
  const filesById = useRef(new Map<string, File>());

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    );
  }, []);

  const send = useCallback(
    async (id: string, file: File) => {
      patch(id, {
      state: "UPLOADING",
      percent: 0,
      error: null,
      errorStatus: null,
      retryable: false,
    });
      try {
        const document = await apiUpload<SourceDocument>(path, file, {
          onProgress: ({ percent }) => patch(id, { percent }),
          onUploaded: () => patch(id, { state: "PROCESSING", percent: 100 }),
        });
        patch(id, {
          state: READABLE.has(document.status) ? "READY" : "UPLOADED",
          percent: 100,
          documentId: document.id,
        });
        queryClient.invalidateQueries({ queryKey: queryKeys.documents(caseId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.caseAudit(caseId) });
        onUploaded?.(document);
      } catch (caught) {
        const error = caught instanceof ApiError ? caught : null;
        patch(id, {
          state: "FAILED",
          error: error?.message ?? "Upload failed.",
          errorStatus: error?.status ?? null,
          // A 4xx other than "too many requests" is a verdict on these bytes;
          // resending them changes nothing. Network and 5xx failures might.
          retryable: !error || error.status >= 500 || error.status === 0 || error.status === 429,
        });
      }
    },
    [caseId, onUploaded, patch, path, queryClient],
  );

  const enqueue = useCallback(
    (files: File[]) => {
      const queued: UploadItem[] = [];
      for (const file of files) {
        const id = nextId();
        filesById.current.set(id, file);
        const problem = duplicateCheck?.(file) ?? validateFile(file, limits);
        queued.push({
          id,
          file,
          name: file.name,
          size: file.size,
          state: problem ? "FAILED" : "SELECTED",
          percent: null,
          error: problem,
          errorStatus: null,
          retryable: false,
          documentId: null,
        });
      }
      setItems((current) => [...current, ...queued]);
      for (const item of queued) {
        if (item.state === "SELECTED") void send(item.id, item.file);
      }
    },
    [duplicateCheck, limits, send],
  );

  const retry = useCallback(
    (id: string) => {
      const file = filesById.current.get(id);
      if (!file) return;
      const problem = validateFile(file, limits);
      if (problem) {
        patch(id, { state: "FAILED", error: problem });
        return;
      }
      void send(id, file);
    },
    [limits, patch, send],
  );

  const dismiss = useCallback((id: string) => {
    filesById.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const busy = items.some(
    (item) => item.state === "UPLOADING" || item.state === "PROCESSING",
  );

  return { items, enqueue, retry, dismiss, busy };
}
