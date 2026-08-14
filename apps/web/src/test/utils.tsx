import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";

/** A response the fetch mock should return for a given route. */
export interface MockResponse {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  /**
   * Server-sent-event frames, delivered one chunk at a time. Set this instead
   * of `body` for the jobs event stream: `streamJobEvents` reads the response
   * through `body.getReader()`, which a plain JSON `Response` does not offer.
   */
  stream?: string[];
}

export type RouteTable = Record<string, MockResponse | ((init?: RequestInit) => MockResponse)>;

export interface FetchCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

/**
 * Install a fetch mock keyed by "METHOD /path". Returns the recorded calls so
 * tests can assert on what was actually sent (auth headers, request bodies).
 */
export function mockApi(routes: RouteTable): FetchCall[] {
  const calls: FetchCall[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const { pathname, search } = new URL(url);

      calls.push({
        url,
        method,
        headers: (init?.headers ?? {}) as Record<string, string>,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });

      const candidates = [
        `${method} ${pathname}${search}`,
        `${method} ${pathname}`,
        `${pathname}${search}`,
        pathname,
      ];
      const match = candidates.map((key) => routes[key]).find(Boolean);

      if (!match) {
        return new Response(JSON.stringify({ detail: `no mock for ${method} ${pathname}` }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }

      const resolved = typeof match === "function" ? match(init) : match;
      const status = resolved.status ?? 200;

      if (resolved.stream) {
        return sseResponse(resolved.stream);
      }

      return new Response(resolved.body === undefined ? null : JSON.stringify(resolved.body), {
        status,
        headers: { "Content-Type": "application/json", ...(resolved.headers ?? {}) },
      });
    }),
  );

  return calls;
}

/** The smallest object `streamJobEvents` needs: `ok` and a chunk reader. */
function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? { done: false, value: encoder.encode(chunks[index++]) }
            : { done: true, value: undefined },
      }),
    },
  } as unknown as Response;
}

export interface UploadCall {
  url: string;
  headers: Record<string, string>;
  fileNames: string[];
}

/**
 * Stub XMLHttpRequest, which is what `apiUpload` uses so it can report real
 * request-body progress. The fake drives the same event sequence the browser
 * does — progress, then upload load, then response — so a component's
 * UPLOADING → PROCESSING → READY transitions are exercised rather than skipped.
 */
export function mockXhrUpload(
  respond: (call: UploadCall) => { status: number; body?: unknown },
): UploadCall[] {
  const calls: UploadCall[] = [];

  class FakeXhr {
    status = 0;
    responseText = "";
    upload: { onprogress?: (event: ProgressEvent) => void; onload?: () => void } = {};
    onload?: () => void;
    onerror?: () => void;
    ontimeout?: () => void;
    onabort?: () => void;
    private url = "";
    private headers: Record<string, string> = {};

    open(_method: string, url: string) {
      this.url = url;
    }

    setRequestHeader(key: string, value: string) {
      this.headers[key] = value;
    }

    abort() {
      this.onabort?.();
    }

    send(form: FormData) {
      const fileNames = form
        .getAll("file")
        .map((entry) => (entry instanceof File ? entry.name : String(entry)));
      const call: UploadCall = { url: this.url, headers: this.headers, fileNames };
      calls.push(call);

      const result = respond(call);
      // Each hop is its own task so React can render the intermediate state.
      setTimeout(() => {
        this.upload.onprogress?.({
          loaded: 50,
          total: 100,
          lengthComputable: true,
        } as ProgressEvent);
        setTimeout(() => {
          this.upload.onload?.();
          setTimeout(() => {
            this.status = result.status;
            this.responseText = result.body === undefined ? "" : JSON.stringify(result.body);
            this.onload?.();
          }, 0);
        }, 0);
      }, 0);
    }
  }

  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  return calls;
}

export function Wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui: ReactElement, options?: RenderOptions) {
  return render(ui, { wrapper: Wrapper, ...options });
}
