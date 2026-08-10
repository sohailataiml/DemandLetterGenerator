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
      return new Response(resolved.body === undefined ? null : JSON.stringify(resolved.body), {
        status,
        headers: { "Content-Type": "application/json", ...(resolved.headers ?? {}) },
      });
    }),
  );

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
