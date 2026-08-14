"use client";

/** One in-flight upload: its state, its progress, and its way out of failure. */

import { Badge, Button, Note } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { BadgeTone } from "@/components/ui/primitives";
import type { UploadItem, UploadState } from "./queue";

const STATE_LABEL: Record<UploadState, string> = {
  SELECTED: "Queued",
  UPLOADING: "Uploading",
  PROCESSING: "Processing evidence",
  UPLOADED: "Stored — text not readable",
  READY: "Ready for extraction",
  FAILED: "Upload failed",
};

const STATE_TONE: Record<UploadState, BadgeTone> = {
  SELECTED: "muted",
  UPLOADING: "accent",
  PROCESSING: "accent",
  UPLOADED: "warning",
  READY: "success",
  FAILED: "danger",
};

export function UploadProgressBar({ percent }: { percent: number | null }) {
  const indeterminate = percent === null;
  return (
    <div
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Upload progress"
      className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-line-soft"
    >
      <div
        className={cn(
          "h-full rounded bg-accent-600 transition-[width] duration-200",
          indeterminate && "animate-pulse",
        )}
        style={{ width: indeterminate ? "100%" : `${percent}%` }}
      />
    </div>
  );
}

export function UploadRow({
  item,
  onRetry,
  onDismiss,
}: {
  item: UploadItem;
  onRetry: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const inFlight = item.state === "UPLOADING" || item.state === "PROCESSING";

  return (
    <li className="px-4 py-2.5" data-testid={`upload-${item.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 truncate text-body font-medium text-ink">{item.name}</span>
        <Badge tone={STATE_TONE[item.state]} strong>
          {STATE_LABEL[item.state]}
        </Badge>
        <span className="text-2xs text-ink-faint">{formatBytes(item.size)}</span>
      </div>

      {item.state === "UPLOADING" ? (
        <>
          <UploadProgressBar percent={item.percent} />
          <p className="mt-1 text-2xs text-ink-faint">
            {item.percent === null ? "Sending…" : `${item.percent}%`}
          </p>
        </>
      ) : null}

      {item.state === "PROCESSING" ? (
        <>
          <UploadProgressBar percent={null} />
          <p className="mt-1 text-2xs text-ink-faint">
            Scanning the file and reading its text.
          </p>
        </>
      ) : null}

      {item.state === "UPLOADED" ? (
        <div className="mt-1">
          <Note>
            The file is stored, but no text could be read from it — a scanned document needs OCR
            before facts can be extracted from it.
          </Note>
        </div>
      ) : null}

      {item.state === "FAILED" && item.error ? (
        <div className="mt-1.5 rounded border border-stop-200 bg-stop-50 px-3 py-2">
          <p className="text-meta text-stop-800">{item.error}</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {/* Offered only where resending could actually change the outcome. */}
            {item.retryable ? (
              <Button size="sm" variant="secondary" onClick={() => onRetry(item.id)}>
                Retry
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => onDismiss(item.id)}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : null}

      {!inFlight && item.state !== "FAILED" ? (
        <div className="mt-1.5">
          <Button size="sm" variant="ghost" onClick={() => onDismiss(item.id)}>
            Clear from list
          </Button>
        </div>
      ) : null}
    </li>
  );
}
