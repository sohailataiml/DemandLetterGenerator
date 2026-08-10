"use client";

import { useState } from "react";

import { ApiError, apiDownload, saveBlob } from "@/lib/api/client";
import { Button } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import type { Demand } from "@/lib/api/types";

/** Shown verbatim when the backend has no PDF converter. Never a fake PDF. */
export const PDF_UNAVAILABLE_MESSAGE =
  "PDF conversion is unavailable in this development environment. DOCX remains available.";

/** Download handling shared by the case header and the demand toolbar. */
export function useDemandDownloads(demandId: string | undefined) {
  const toast = useToast();
  const [pdfUnavailable, setPdfUnavailable] = useState<string | null>(null);
  const [busy, setBusy] = useState<"docx" | "pdf" | null>(null);

  const downloadDocx = async () => {
    if (!demandId) return;
    setBusy("docx");
    try {
      const file = await apiDownload(`/v1/demands/${demandId}/docx`);
      saveBlob(file.blob, file.filename);
      toast.push({
        tone: "success",
        title: "DOCX generated",
        description: file.sha256 ? `SHA-256 ${file.sha256.slice(0, 12)}…` : undefined,
      });
    } catch (caught) {
      toast.push({
        tone: "error",
        title: "DOCX failed",
        description: caught instanceof ApiError ? caught.message : String(caught),
      });
    } finally {
      setBusy(null);
    }
  };

  const downloadPdf = async () => {
    if (!demandId) return;
    setBusy("pdf");
    setPdfUnavailable(null);
    try {
      const file = await apiDownload(`/v1/demands/${demandId}/pdf`);
      saveBlob(file.blob, file.filename);
      toast.push({ tone: "success", title: "PDF generated" });
    } catch (caught) {
      if (caught instanceof ApiError && caught.isUnavailable) {
        setPdfUnavailable(PDF_UNAVAILABLE_MESSAGE);
        toast.push({
          tone: "info",
          title: "PDF unavailable",
          description: "LibreOffice is not installed. The DOCX is unaffected.",
        });
      } else {
        toast.push({
          tone: "error",
          title: "PDF failed",
          description: caught instanceof ApiError ? caught.message : String(caught),
        });
      }
    } finally {
      setBusy(null);
    }
  };

  return { downloadDocx, downloadPdf, pdfUnavailable, busy };
}

/**
 * Final-document actions for an approved demand. These are the actions that
 * matter once a case is locked, so they sit next to the case identity.
 */
export function FinalDocumentActions({
  demand,
  onView,
}: {
  demand: Demand;
  onView?: () => void;
}) {
  const { downloadDocx, downloadPdf, pdfUnavailable, busy } = useDemandDownloads(demand.id);

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {onView ? (
          <Button variant="primary" size="sm" onClick={onView}>
            View Final Demand
          </Button>
        ) : null}
        <Button size="sm" disabled={busy === "docx"} onClick={downloadDocx}>
          Download DOCX
        </Button>
        <Button size="sm" disabled={busy === "pdf"} onClick={downloadPdf}>
          Download PDF
        </Button>
      </div>
      {pdfUnavailable ? (
        <p className="max-w-xs text-right text-2xs leading-4 text-warn-700">{pdfUnavailable}</p>
      ) : null}
    </div>
  );
}
