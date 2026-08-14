import { describe, expect, it } from "vitest";

import { ApiError, apiDownload, apiFetch, authHeaders } from "./client";
import { mockApi } from "@/test/utils";

describe("api client", () => {
  it("sends the configured auth headers on every request", async () => {
    const calls = mockApi({ "/v1/cases": { body: [] } });

    await apiFetch("/v1/cases");

    expect(calls).toHaveLength(1);
    expect(calls[0].headers["X-User-Id"]).toBe(authHeaders()["X-User-Id"]);
    expect(calls[0].headers["X-User-Role"]).toBe(authHeaders()["X-User-Role"]);
  });

  it("serializes bodies as JSON with a content type", async () => {
    const calls = mockApi({ "POST /v1/facts/f1/reject": { body: {} } });

    await apiFetch("/v1/facts/f1/reject", { method: "POST", body: { reason: "unsupported" } });

    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({ reason: "unsupported" });
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
  });

  it("turns a 403 into an ApiError flagged as an auth failure", async () => {
    mockApi({ "/v1/cases": { status: 403, body: { detail: "role may not perform this action" } } });

    const error = (await apiFetch("/v1/cases").catch((caught) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.isAuth).toBe(true);
    expect(error.message).toBe("role may not perform this action");
  });

  it("exposes blocking issues carried by a 409 from approval", async () => {
    mockApi({
      "POST /v1/demands/d1/approve": {
        status: 409,
        body: {
          detail: {
            message: "1 blocking validation issue(s) must be resolved before approval",
            blocking_issues: [
              { code: "NARRATIVE_002", message: "Section was not drafted", section_key: "liability" },
            ],
          },
        },
      },
    });

    const error = (await apiFetch("/v1/demands/d1/approve", { method: "POST" }).catch(
      (c) => c,
    )) as ApiError;

    expect(error.isConflict).toBe(true);
    expect(error.blockingIssues).toHaveLength(1);
    expect(error.blockingIssues[0].code).toBe("NARRATIVE_002");
  });

  it("flags a 503 as unavailable rather than a failure", async () => {
    mockApi({
      "/v1/demands/d1/pdf": {
        status: 503,
        body: { detail: "PDF generation requires LibreOffice ('soffice') on PATH." },
      },
    });

    const error = (await apiDownload("/v1/demands/d1/pdf").catch((caught) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isUnavailable).toBe(true);
  });

  it("reports an unreachable backend without throwing a raw network error", async () => {
    const { vi } = await import("vitest");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const error = (await apiFetch("/v1/cases").catch((caught) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.message).toContain("Is the backend running?");
  });

  it("reads the filename and hash from download headers", async () => {
    mockApi({
      "/v1/demands/d1/docx": {
        body: { ok: true },
        headers: {
          "Content-Disposition": 'attachment; filename="draft-v2.docx"',
          "X-Content-SHA256": "abc123",
        },
      },
    });

    const file = await apiDownload("/v1/demands/d1/docx");

    expect(file.filename).toBe("draft-v2.docx");
    expect(file.sha256).toBe("abc123");
  });
});
