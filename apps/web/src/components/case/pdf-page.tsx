"use client";

/**
 * One page of an original PDF, rendered in the browser.
 *
 * The original file is the evidence; extracted text is only an index of it. So
 * this draws the actual page the attorney would see on paper, and the citation
 * overlay is positioned on top of it in normalized coordinates — no server-side
 * rasterizing, no altered PDF, and the bytes never leave the tab's memory.
 *
 * PDF.js is imported dynamically because it is large and only ever needed when
 * somebody opens evidence. If it cannot load — an old browser, a missing worker
 * asset — this reports `unavailable` and the viewer falls back to showing the
 * extracted page text, which is a poorer view but never a false one.
 */

import { useEffect, useRef, useState } from "react";

import { apiFetchBytes } from "@/lib/api/client";

export type PdfPageState = "loading" | "ready" | "unavailable";

export interface PdfPageProps {
  documentId: string;
  pageNumber: number;
  /** Rendering width in CSS pixels; the page keeps its own aspect ratio. */
  width?: number;
  onStateChange?: (state: PdfPageState, detail?: string) => void;
}

const WORKER_SRC = "/pdf.worker.min.mjs";

export function PdfPage({ documentId, pageNumber, width = 720, onStateChange }: PdfPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<PdfPageState>("loading");

  // Held in a ref so a caller passing an inline arrow does not restart the
  // render on every parent re-render — re-rendering a PDF page is expensive.
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const report = (next: PdfPageState, detail?: string) => {
      if (cancelled) return;
      setState(next);
      onStateChangeRef.current?.(next, detail);
    };

    report("loading");

    (async () => {
      try {
        const [pdfjs, data] = await Promise.all([
          import("pdfjs-dist"),
          apiFetchBytes(`/v1/documents/${documentId}/content`, controller.signal),
        ]);
        if (cancelled) return;

        pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC;
        const document = await pdfjs.getDocument({ data }).promise;
        const page = await document.getPage(pageNumber);
        const canvas = canvasRef.current;
        if (cancelled || !canvas) {
          document.destroy();
          return;
        }

        // Render at device resolution, lay out at CSS resolution, so the page
        // is crisp and the overlay's percentages still line up exactly.
        const ratio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: (width * ratio) / base.width });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = "100%";
        canvas.style.height = "auto";

        await page.render({ canvas, viewport }).promise;
        document.destroy();
        report("ready");
      } catch (error) {
        if (cancelled) return;
        report("unavailable", error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [documentId, pageNumber, width]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="pdf-page-canvas"
      data-state={state}
      aria-label={`Page ${pageNumber} of the original document`}
      role="img"
      className="block w-full"
    />
  );
}

export default PdfPage;
