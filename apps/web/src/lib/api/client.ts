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
