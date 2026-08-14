/**
 * The single place the app talks to FastAPI.
 *
 * Every request carries the development auth headers, and every non-2xx
 * response becomes an ApiError carrying the status and the backend's own detail
 * so callers can distinguish 403 from 409 from 503 without re-parsing bodies.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export const AUTH_USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "attorney_1";
export const AUTH_USER_ROLE = process.env.NEXT_PUBLIC_USER_ROLE ?? "attorney";

export function authHeaders(): Record<string, string> {
  return {
    "X-User-Id": AUTH_USER_ID,
    "X-User-Role": AUTH_USER_ROLE,
  };
}

/** Blocking issues returned alongside a 409 from the approval endpoint. */
export interface BlockingIssueDetail {
  code: string;
  message: string;
  section_key: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isAuth(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }

  /** 503 from the PDF endpoint means no converter is installed, not a crash. */
  get isUnavailable(): boolean {
    return this.status === 503;
  }

  get blockingIssues(): BlockingIssueDetail[] {
    const detail = this.detail as { blocking_issues?: BlockingIssueDetail[] } | undefined;
    return detail?.blocking_issues ?? [];
  }
}

function messageFromDetail(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const asRecord = detail as Record<string, unknown>;
    if (typeof asRecord.message === "string") return asRecord.message;
    // FastAPI request-validation errors: [{loc, msg, type}, ...]
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string; loc?: unknown[] };
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
        return field ? `${field}: ${first.msg}` : first.msg;
      }
    }
  }
  if (status === 401) return "Authentication required.";
  if (status === 403) return "Your role does not permit this action.";
  return `Request failed (${status}).`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal,
      headers: {
        ...authHeaders(),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    throw new ApiError(
      0,
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
      cause,
    );
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      const payload = await response.json();
      detail = (payload as { detail?: unknown })?.detail ?? payload;
    } catch {
      detail = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, messageFromDetail(response.status, detail), detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ------------------------------------------------------------------- uploads

export interface UploadProgress {
  loaded: number;
  total: number;
  /** 0–100, or null while the total length is unknown. */
  percent: number | null;
}

export interface UploadOptions {
  /** Extra multipart form fields sent alongside the file. */
  fields?: Record<string, string>;
  onProgress?: (progress: UploadProgress) => void;
  /** Fires once the last byte is sent — from here the server is working. */
  onUploaded?: () => void;
  signal?: AbortSignal;
}

/**
 * Multipart upload with real progress.
 *
 * XMLHttpRequest rather than fetch: fetch reports nothing about request-body
 * progress, and a progress bar that jumps 0→100 is worse than none on a 40MB
 * medical record. `onUploaded` marks the moment the bytes are delivered, which
 * is when the server starts extracting text — so the UI can distinguish
 * "uploading" from "the server is working" without inventing either.
 */
export function apiUpload<T>(path: string, file: File, options: UploadOptions = {}): Promise<T> {
  const { fields = {}, onProgress, onUploaded, signal } = options;

  return new Promise<T>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    for (const [key, value] of Object.entries(fields)) form.append(key, value);

    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE_URL}${path}`);
    for (const [key, value] of Object.entries(authHeaders())) {
      request.setRequestHeader(key, value);
    }

    request.upload.onprogress = (event) => {
      onProgress?.({
        loaded: event.loaded,
        total: event.total,
        percent: event.lengthComputable ? Math.round((event.loaded / event.total) * 100) : null,
      });
    };
    request.upload.onload = () => onUploaded?.();

    request.onload = () => {
      let payload: unknown = null;
      try {
        payload = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        payload = request.responseText;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as T);
        return;
      }
      const detail = (payload as { detail?: unknown })?.detail ?? payload;
      reject(new ApiError(request.status, messageFromDetail(request.status, detail), detail));
    };
    request.onerror = () =>
      reject(new ApiError(0, `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`, null));
    request.ontimeout = () => reject(new ApiError(0, "The upload timed out.", null));
    request.onabort = () => reject(new ApiError(0, "Upload cancelled.", null));

    signal?.addEventListener("abort", () => request.abort(), { once: true });
    request.send(form);
  });
}

// --------------------------------------------------------------- job progress

export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental parser for the `event:`/`data:` frames the jobs endpoint emits.
 *
 * Kept separate from the transport because a network chunk boundary can land
 * anywhere — including mid-frame — and that is exactly the case worth having a
 * test for. Feed it whatever arrives; it returns only complete events.
 */
export function createEventStreamParser() {
  let buffer = "";

  return {
    push(chunk: string): SseEvent[] {
      buffer += chunk;
      const events: SseEvent[] = [];
      let boundary = buffer.indexOf("\n\n");

      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");

        let name = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith(":")) continue; // keep-alive comment
          if (line.startsWith("event:")) name = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        }
        if (dataLines.length > 0) events.push({ event: name, data: dataLines.join("\n") });
      }
      return events;
    },
  };
}

export interface JobStreamHandlers {
  onStage?: (stage: { stage: string; status: string; detail?: string; at: string }) => void;
  onDone?: (payload: {
    job_id: string;
    status: string;
    result?: Record<string, unknown> | null;
    error?: string | null;
  }) => void;
}

/**
 * Follow a job's server-sent events to completion.
 *
 * `EventSource` cannot carry the auth headers this API requires, so the stream
 * is read from a normal fetch body. Callers are expected to also hold a polled
 * query on the job row: if this stream dies, progress detail stops but the
 * outcome is still observed.
 */
export async function streamJobEvents(
  jobId: string,
  handlers: JobStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/jobs/${jobId}/events`, {
    headers: { ...authHeaders(), Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, messageFromDetail(response.status, null), null);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createEventStreamParser();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        continue; // a frame we cannot read is not a reason to kill the stream
      }
      if (event.event === "stage") handlers.onStage?.(payload as never);
      if (event.event === "done") {
        handlers.onDone?.(payload as never);
        return;
      }
    }
  }
}

/** Binary download (DOCX/PDF) that preserves the server-provided filename. */
export async function apiDownload(
  path: string,
): Promise<{ blob: Blob; filename: string; sha256: string | null }> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: authHeaders() });

  if (!response.ok) {
    let detail: unknown = null;
    try {
      const payload = await response.json();
      detail = (payload as { detail?: unknown })?.detail ?? payload;
    } catch {
      detail = null;
    }
    throw new ApiError(response.status, messageFromDetail(response.status, detail), detail);
  }

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? path.split("/").pop() ?? "download",
    sha256: response.headers.get("X-Content-SHA256"),
  };
}

/** Trigger a browser save for an already-fetched blob. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
