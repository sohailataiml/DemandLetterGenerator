import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceViewer } from "./source-viewer";
import { CASE_ID, documentDetail, facts, pageGeometry, workspaceRoutes } from "@/test/fixtures";
import { mockApi, renderWithProviders } from "@/test/utils";
import type { RouteTable } from "@/test/utils";
import type { FactSource } from "@/lib/api/types";

const exactCitation = facts[0].sources[0];

/** Stands in for PDF.js: the real canvas cannot render inside jsdom. */
function stubPage({ pageNumber }: { pageNumber: number }) {
  return <div data-testid="stub-page">rendered page {pageNumber}</div>;
}

function open(citation: FactSource | null, routes: RouteTable = workspaceRoutes) {
  const calls = mockApi(routes);
  renderWithProviders(
    <SourceViewer
      caseId={CASE_ID}
      documentId="doc_1"
      pageNumber={citation?.page_number ?? 1}
      citation={citation}
      onClose={() => undefined}
      renderPage={stubPage}
    />,
  );
  return calls;
}

describe("source viewer", () => {
  it("opens the original document at the page the citation names", async () => {
    open(exactCitation);

    expect(await screen.findByTestId("stub-page")).toHaveTextContent("rendered page 2");
    expect(
      screen.getByRole("dialog", { name: /Original source — .*page 2/i }),
    ).toBeInTheDocument();
  });

  it("draws one highlight box per line of an exact citation", async () => {
    open(exactCitation);

    await screen.findByTestId("stub-page");
    const boxes = await screen.findAllByTestId("citation-box");
    expect(boxes).toHaveLength(exactCitation.bounding_boxes!.length);
    // Positioned from the stored normalized coordinates, not recomputed.
    expect(boxes[0]).toHaveStyle({ left: "18%", top: "51%" });
  });

  it("does not fake a highlight for a paraphrased citation", async () => {
    open({
      ...exactCitation,
      citation_status: "TEXT_ONLY",
      match_kind: "approximate",
      bounding_boxes: null,
    });

    await screen.findByTestId("stub-page");
    expect(screen.queryByTestId("citation-box")).not.toBeInTheDocument();
    expect(screen.getByTestId("citation-honesty")).toHaveTextContent(
      /Exact source highlight unavailable/i,
    );
  });

  it("says so when a citation names a page but no passage", async () => {
    open({
      ...exactCitation,
      excerpt: null,
      start_offset: null,
      end_offset: null,
      citation_status: "UNRESOLVED",
      bounding_boxes: null,
    });

    await screen.findByTestId("stub-page");
    expect(screen.queryByTestId("citation-box")).not.toBeInTheDocument();
    expect(screen.getByTestId("citation-honesty")).toHaveTextContent(
      /No passage is recorded for this citation/i,
    );
  });

  it("asks the reviewer to choose when the page repeats the passage", async () => {
    const repeated = {
      ...documentPageWithRepeats(),
    };
    open(
      {
        ...exactCitation,
        excerpt: "disc extrusion",
        start_offset: null,
        end_offset: null,
        citation_status: "AMBIGUOUS",
        bounding_boxes: null,
      },
      { ...workspaceRoutes, "/v1/documents/doc_1/pages/2": { body: repeated } },
    );

    expect(await screen.findByText(/Select supporting passage/i)).toBeInTheDocument();
    const options = await screen.findAllByRole("button", { name: /Occurrence \d/ });
    expect(options).toHaveLength(2);
    // Nothing was resolved on the reviewer's behalf.
    expect(screen.queryByTestId("citation-box")).not.toBeInTheDocument();
  });

  it("sends the reviewer's chosen occurrence as page offsets", async () => {
    const repeated = documentPageWithRepeats();
    const calls = open(
      {
        ...exactCitation,
        excerpt: "disc extrusion",
        start_offset: null,
        end_offset: null,
        citation_status: "AMBIGUOUS",
        bounding_boxes: null,
      },
      {
        ...workspaceRoutes,
        "/v1/documents/doc_1/pages/2": { body: repeated },
        "POST /v1/citations/fsrc_1/resolve": {
          body: { ...exactCitation, citation_status: "EXACT" },
        },
      },
    );
    const user = userEvent.setup();

    const options = await screen.findAllByRole("button", { name: /Occurrence \d/ });
    await user.click(options[1]);
    await user.click(screen.getByRole("button", { name: /Use this passage/i }));

    await waitFor(() => {
      const resolve = calls.find((call) => call.url.includes("/resolve"));
      expect(resolve?.body).toEqual({
        start_offset: repeated.text.lastIndexOf("disc extrusion"),
        end_offset: repeated.text.lastIndexOf("disc extrusion") + "disc extrusion".length,
      });
    });
  });

  it("fetches page geometry lazily — never for a citation that cannot use it", async () => {
    const calls = open(exactCitation);

    await screen.findAllByTestId("citation-box");
    expect(calls.some((call) => call.url.includes("/geometry"))).toBe(false);
  });

  it("fetches page geometry only once a passage has to be placed on the page", async () => {
    const repeated = documentPageWithRepeats();
    const calls = open(
      {
        ...exactCitation,
        excerpt: "disc extrusion",
        citation_status: "AMBIGUOUS",
        bounding_boxes: null,
      },
      {
        ...workspaceRoutes,
        "/v1/documents/doc_1/pages/2": { body: repeated },
        "/v1/documents/doc_1/pages/2/geometry": { body: pageGeometry },
      },
    );

    await screen.findAllByRole("button", { name: /Occurrence \d/ });
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/geometry"))).toBe(true);
    });
  });

  it("falls back to the extracted page text when the original cannot be rendered", async () => {
    mockApi(workspaceRoutes);
    renderWithProviders(
      <SourceViewer
        caseId={CASE_ID}
        documentId="doc_1"
        pageNumber={2}
        citation={exactCitation}
        onClose={() => undefined}
        renderPage={({ onStateChange }) => {
          onStateChange("unavailable", "no worker");
          return null;
        }}
      />,
    );

    expect(
      await screen.findByText(/The original page could not be rendered here/i),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("page-text-highlight")).toHaveTextContent(
      "disc extrusion at L5-S1",
    );
  });

  it("is dismissible from the keyboard", async () => {
    const onClose = vi.fn();
    mockApi(workspaceRoutes);
    const user = userEvent.setup();

    renderWithProviders(
      <SourceViewer
        caseId={CASE_ID}
        documentId="doc_1"
        pageNumber={2}
        citation={exactCitation}
        onClose={onClose}
        renderPage={stubPage}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();

    // And the close control is reachable by keyboard, not mouse-only.
    await user.tab();
    expect(
      within(dialog).getByRole("button", { name: /Close source viewer/i }),
    ).toBeInTheDocument();
  });

  it("pages through the document without leaving the viewer", async () => {
    open(exactCitation);
    const user = userEvent.setup();

    await screen.findByTestId("stub-page");
    await user.click(screen.getByRole("button", { name: /Previous page/i }));

    expect(await screen.findByTestId("stub-page")).toHaveTextContent("rendered page 1");
    expect(screen.getByText(/The citation is on page 2/i)).toBeInTheDocument();
    expect(screen.queryByTestId("citation-box")).not.toBeInTheDocument();
  });
});

function documentPageWithRepeats() {
  return {
    page_number: 2,
    text: "Findings: disc extrusion at L5-S1.\nImpression: disc extrusion at L5-S1.",
    width: 612,
    height: 792,
    extraction_method: "native",
    word_count: 12,
    has_geometry: true,
  };
}

// The fixture document is a PDF, which is what puts the viewer on its rendered
// path rather than its text fallback.
expect(documentDetail.mime_type).toBe("application/pdf");
