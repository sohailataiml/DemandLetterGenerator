import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiPrivacyCard } from "./ai-privacy";
import { renderWithProviders } from "@/test/utils";
import type { GenerationMetadata } from "@/lib/api/types";

const gatewayMetadata: GenerationMetadata = {
  ai_boundary: "secure_gateway",
  upstream_provider: "anthropic",
  upstream_model: "claude-opus-5",
  gateway_request_ids: ["req-1", "req-2"],
  gateway_session_ids: ["sess-1"],
  privacy: {
    detected: 8,
    tokenized: 3,
    pseudonymized: 4,
    redacted: 1,
    blocked: 0,
    restored: 3,
    entity_types: { PERSON: 4, PHONE_NUMBER: 1 },
  },
  usage: { total_tokens: 1020 },
  latency_ms: 2400,
  calls: 2,
  sections: {
    imaging_summary: {
      gateway_request_id: "req-1",
      protected_preview: {
        // Masked by the gateway before it ever reaches a browser.
        text: "Client: ⟦PERSON:••••⟧ at ⟦LOCATION:••••⟧. Imaging showed a disc extrusion at L5-S1.",
        entity_summary: [
          { entity_type: "PERSON", count: 1, action: "tokenize" },
          { entity_type: "LOCATION", count: 1, action: "tokenize" },
        ],
        outbound_scan: "passed",
        truncated: false,
      },
    },
  },
};

describe("AI privacy card", () => {
  it("shows the secure gateway badge and the counts it reported", () => {
    renderWithProviders(<AiPrivacyCard metadata={gatewayMetadata} />);

    expect(screen.getByText(/Secure Gateway/)).toBeInTheDocument();
    expect(screen.getByTestId("privacy-detected")).toHaveTextContent("8");
    expect(screen.getByTestId("privacy-tokenized")).toHaveTextContent("3");
    expect(screen.getByTestId("privacy-pseudonymized")).toHaveTextContent("4");
    expect(screen.getByTestId("privacy-redacted")).toHaveTextContent("1");
    expect(screen.getByTestId("privacy-blocked")).toHaveTextContent("0");
  });

  it("names entity types and counts, never values", () => {
    renderWithProviders(<AiPrivacyCard metadata={gatewayMetadata} />);

    const card = screen.getByTestId("ai-privacy");
    expect(card).toHaveTextContent("person · 4");
    expect(card).toHaveTextContent("phone number · 1");
    // Nothing that could be a detected value, a token, or a session secret.
    expect(card.textContent).not.toMatch(/@|\+?\d{3}[-.]\d{3}[-.]\d{4}/);
    expect(card.textContent).not.toContain("sess-1");
  });

  it("says plainly when a draft bypassed the privacy gateway", () => {
    renderWithProviders(
      <AiPrivacyCard metadata={{ ai_boundary: "direct_provider", upstream_model: "claude-opus-5" }} />,
    );

    expect(screen.getByText(/bypassing the privacy gateway/i)).toBeInTheDocument();
  });

  it("reports a local draft as never having left the system", () => {
    renderWithProviders(<AiPrivacyCard metadata={{ ai_boundary: "local" }} />);

    expect(screen.getByText(/Nothing left this system/i)).toBeInTheDocument();
    expect(screen.queryByTestId("privacy-detected")).not.toBeInTheDocument();
  });

  it("renders nothing rather than reassuring zeros when metadata is absent", () => {
    renderWithProviders(<AiPrivacyCard metadata={null} />);

    expect(screen.queryByTestId("ai-privacy")).not.toBeInTheDocument();
    expect(screen.queryByText(/privacy/i)).not.toBeInTheDocument();
  });

  it("shows what the provider saw and what came back, collapsed by default", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AiPrivacyCard
        metadata={gatewayMetadata}
        sectionKey="imaging_summary"
        restoredText="Imaging showed a disc extrusion at L5-S1, per Jane Example's MRI."
      />,
    );

    // Collapsed: the transcript exists but is not open.
    const transcript = screen.getByTestId("boundary-transcript");
    expect(transcript).not.toHaveAttribute("open");

    await user.click(screen.getByText(/What the model actually saw/i));

    // Sent side: masked, and the real value is nowhere in it.
    const sent = screen.getByTestId("protected-sent");
    expect(sent).toHaveTextContent("⟦PERSON:••••⟧");
    expect(sent).not.toHaveTextContent("Jane Example");
    expect(screen.getByText(/person · tokenize · 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Outbound scan: passed/i)).toBeInTheDocument();

    // Received side: the restored prose the attorney is authorized to read.
    expect(screen.getByTestId("restored-received")).toHaveTextContent("Jane Example");
  });

  it("explains a truncated preview instead of looking self-contradictory", async () => {
    const user = userEvent.setup();
    const truncated: GenerationMetadata = {
      ...gatewayMetadata,
      sections: {
        imaging_summary: {
          gateway_request_id: "req-1",
          protected_preview: {
            // The gateway cut the preview before the masked values, so the
            // visible slice carries no ⟦TYPE:••••⟧ marker at all.
            text: "You are drafting one section of a personal injury demand letter…",
            entity_summary: [{ entity_type: "PERSON", count: 1, action: "tokenize" }],
            outbound_scan: "passed",
            truncated: true,
          },
        },
      },
    };
    renderWithProviders(
      <AiPrivacyCard metadata={truncated} sectionKey="imaging_summary" restoredText="Prose." />,
    );

    await user.click(screen.getByText(/What the model actually saw/i));

    expect(screen.getByTestId("preview-truncated")).toHaveTextContent(
      /truncated this preview at 64 characters/i,
    );
    expect(screen.getByTestId("preview-truncated")).toHaveTextContent(/past the cut/i);
  });

  it("does not claim values are past the cut when the slice shows them", async () => {
    const user = userEvent.setup();
    const truncated: GenerationMetadata = {
      ...gatewayMetadata,
      sections: {
        imaging_summary: {
          protected_preview: {
            text: "Client: ⟦PERSON:••••⟧ and more prompt after this…",
            entity_summary: [{ entity_type: "PERSON", count: 1, action: "tokenize" }],
            outbound_scan: "passed",
            truncated: true,
          },
        },
      },
    };
    renderWithProviders(
      <AiPrivacyCard metadata={truncated} sectionKey="imaging_summary" restoredText="Prose." />,
    );

    await user.click(screen.getByText(/What the model actually saw/i));

    expect(screen.getByTestId("preview-truncated")).toHaveTextContent(/rest of the prompt is not shown/i);
    expect(screen.getByTestId("preview-truncated")).not.toHaveTextContent(/past the cut/i);
  });

  it("omits the transcript when the deployment sends no preview", () => {
    renderWithProviders(
      <AiPrivacyCard
        metadata={{ ai_boundary: "secure_gateway", privacy: { detected: 1 } }}
        sectionKey="imaging_summary"
        restoredText="Some drafted prose."
      />,
    );

    expect(screen.queryByTestId("boundary-transcript")).not.toBeInTheDocument();
  });

  it("omits the transcript for a section that was not drafted through the gateway", () => {
    renderWithProviders(
      <AiPrivacyCard metadata={gatewayMetadata} sectionKey="damages" restoredText="Totals." />,
    );

    expect(screen.queryByTestId("boundary-transcript")).not.toBeInTheDocument();
  });

  it("degrades cleanly when the gateway reported no summary", () => {
    renderWithProviders(<AiPrivacyCard metadata={{ ai_boundary: "secure_gateway" }} />);

    expect(screen.getByText(/no privacy summary/i)).toBeInTheDocument();
    expect(screen.queryByTestId("privacy-detected")).not.toBeInTheDocument();
  });
});

/**
 * Architectural, not behavioural: the browser bundle must never talk to the
 * gateway. The credential lives in FastAPI, and a fetch from here would both
 * leak it and hit CORS — so the guarantee is enforced by there being no such
 * call in the source at all.
 */
describe("the browser never calls the secure gateway", () => {
  function sourceFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((entry) => {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) return sourceFiles(path);
      return /\.(ts|tsx|mjs|js)$/.test(entry) ? [path] : [];
    });
  }

  // The two test files that *assert* on the host name are excluded; nothing
  // else in the bundle may mention it.
  const files = sourceFiles(join(process.cwd(), "src")).filter(
    (path) =>
      !path.endsWith("ai-privacy.test.tsx") && !path.endsWith("demand-gateway.test.tsx"),
  );

  it("has no reference to the gateway host in any frontend source file", () => {
    const offenders = files.filter((path) =>
      readFileSync(path, "utf8").includes("sgw-api.onrender.com"),
    );

    expect(offenders).toEqual([]);
  });

  it("never reads a gateway credential from the environment", () => {
    const offenders = files.filter((path) => {
      const source = readFileSync(path, "utf8");
      return (
        source.includes("SECURE_GATEWAY_API_KEY") ||
        source.includes("NEXT_PUBLIC_SECURE_GATEWAY")
      );
    });

    expect(offenders).toEqual([]);
  });

  it("sends every request to the app's own API base URL", async () => {
    const { API_BASE_URL } = await import("@/lib/api/client");

    expect(API_BASE_URL).not.toContain("sgw-api");
  });
});
