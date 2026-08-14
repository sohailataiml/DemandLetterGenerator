"use client";

/**
 * Section A of Documents: the attorney's own demand letter.
 *
 * This file has a different job from every other upload on the page. It is not
 * evidence and no fact is ever drawn from it — it is the container the finished
 * letter is written into, which is why it gets its own card, its own copy, and
 * a `.docx`-only picker rather than a "document type" dropdown someone could
 * get wrong.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, apiUpload } from "@/lib/api/client";
import { queryKeys, useTemplateDetail, useTemplates, useUploadLimits } from "@/lib/api/hooks";
import { formatBytes, formatDateTime, shortHash } from "@/lib/format";
import {
  Badge,
  Button,
  Disclosure,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { Dropzone } from "./dropzone";
import { UploadProgressBar } from "./upload-row";
import { limitsForTemplate, validateFile } from "./queue";
import type { LetterTemplate } from "@/lib/api/types";

type Phase = "idle" | "uploading" | "analyzing";

export function TemplateCard({ caseId }: { caseId: string }) {
  const templatesQuery = useTemplates(caseId);
  const limitsQuery = useUploadLimits();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>("idle");
  const [percent, setPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);

  // Most recent first, from the backend's own ordering.
  const template: LetterTemplate | undefined = templatesQuery.data?.[0];
  const detailQuery = useTemplateDetail(template?.id ?? null);
  const limits = limitsForTemplate(limitsQuery.data);

  const upload = async (files: File[]) => {
    const file = files[0];
    if (!file) return;

    const problem = validateFile(file, limits);
    if (problem) {
      setError(problem);
      return;
    }

    setError(null);
    setPhase("uploading");
    setPercent(0);
    try {
      await apiUpload(`/v1/cases/${caseId}/templates`, file, {
        onProgress: ({ percent: value }) => setPercent(value),
        // Analysis happens inside the POST: the server opens the OOXML, walks
        // its blocks and digests every part that carries formatting.
        onUploaded: () => setPhase("analyzing"),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.templates(caseId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.caseAudit(caseId) });
      setReplacing(false);
      toast.push({
        tone: "success",
        title: "Template analyzed",
        description: `${file.name} is ready to receive the letter.`,
      });
    } catch (caught) {
      const message =
        caught instanceof ApiError
          ? caught.status === 409
            ? "That exact template is already on file for this case."
            : caught.message
          : "Upload failed.";
      setError(message);
    } finally {
      setPhase("idle");
      setPercent(null);
    }
  };

  const accept = (limits?.extensions ?? [".docx"]).join(",");
  const busy = phase !== "idle";
  const showDropzone = !template || replacing;

  return (
    <Panel>
      <PanelHeader
        title="Demand letter template"
        description="The original attorney Word document controls the final letter's structure and formatting. Nothing in it is treated as evidence."
        actions={
          template ? (
            <Badge tone="success" strong>
              Ready
            </Badge>
          ) : (
            <Badge tone="warning" strong>
              Required
            </Badge>
          )
        }
      />

      {templatesQuery.isLoading ? <SkeletonRows rows={2} /> : null}

      {showDropzone && !templatesQuery.isLoading ? (
        <>
          <Dropzone
            id="template-upload"
            label="Drop the Word template here"
            hint={
              limits
                ? `.DOCX only · up to ${formatBytes(limits.maxBytes)}`
                : ".DOCX only"
            }
            buttonLabel="Choose template"
            accept={accept}
            disabled={busy}
            busy={busy}
            onFiles={upload}
          />
          {replacing ? (
            <div className="px-4 pb-3">
              <Button size="sm" variant="ghost" onClick={() => setReplacing(false)}>
                Keep the current template
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      {busy ? (
        <div className="px-4 pb-3">
          <UploadProgressBar percent={phase === "analyzing" ? null : percent} />
          <p className="mt-1 text-2xs text-ink-faint">
            {phase === "analyzing"
              ? "Reading the document's structure, styles, headers and footers."
              : `Uploading${percent === null ? "…" : ` ${percent}%`}`}
          </p>
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="mx-4 mb-3 rounded border border-stop-200 bg-stop-50 px-3 py-2">
          <p className="text-meta text-stop-800">{error}</p>
        </div>
      ) : null}

      {template ? (
        <div className="border-t border-line-soft px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-body font-medium text-ink">{template.original_filename}</span>
            <Badge tone="success">Analyzed</Badge>
          </div>

          <dl className="mt-2.5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Figure label="Blocks detected" value={String(template.block_count)} />
            <Figure
              label="Dynamic regions"
              value={
                detailQuery.data ? String(detailQuery.data.slots.length) : "—"
              }
              hint={detailQuery.data ? "places case data is written" : "loading"}
            />
            <Figure
              label="Fingerprint"
              value={shortHash(template.sha256)}
              hint="SHA-256 of the uploaded bytes"
              mono
            />
            <Figure
              label="Uploaded"
              value={formatDateTime(template.created_at)}
              hint={`by ${template.uploaded_by}`}
            />
          </dl>

          {detailQuery.data && detailQuery.data.unknown_slots.length > 0 ? (
            <div className="mt-2.5 rounded border border-warn-200 bg-warn-50 px-3 py-2">
              <p className="text-meta text-warn-800">
                {detailQuery.data.unknown_slots.length} placeholder(s) in this template have no
                case data behind them. Generation will refuse rather than print a placeholder:{" "}
                <span className="font-mono">{detailQuery.data.unknown_slots.join(", ")}</span>
              </p>
            </div>
          ) : null}

          {detailQuery.data ? (
            <Disclosure summary="What the analyzer found" className="mt-3">
              <dl className="grid gap-x-6 gap-y-2 text-meta sm:grid-cols-2">
                <Detail
                  label="Sections"
                  value={
                    detailQuery.data.sections.length > 0
                      ? detailQuery.data.sections.map((s) => s.title).join(" · ")
                      : "none marked"
                  }
                />
                <Detail
                  label="Headers / footers preserved"
                  value={`${detailQuery.data.header_parts.length} header(s), ${detailQuery.data.footer_parts.length} footer(s)`}
                />
                <Detail label="Size" value={formatBytes(template.size_bytes)} />
                <Detail
                  label="Structure fingerprint"
                  value={shortHash(template.structure_sha256)}
                />
              </dl>
              <div className="mt-2.5">
                <Note>
                  The letter is written into a copy of this file. Styles, numbering, page setup
                  and every untouched paragraph keep the exact XML they arrived with, and that is
                  re-checked before a demand can be approved.
                </Note>
              </div>
            </Disclosure>
          ) : null}

          {!showDropzone ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => setReplacing(true)}>
                Replace template
              </Button>
            </div>
          ) : null}
          <p className="mt-2 text-2xs text-ink-faint">
            Replacing uploads a new template. The existing one is kept on file — an approved
            demand always keeps the template it was built from.
          </p>
        </div>
      ) : null}
    </Panel>
  );
}

function Figure({
  label,
  value,
  hint,
  mono = false,
}: {
  label: string;
  value: string;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="metric-label">{label}</dt>
      <dd
        className={`mt-0.5 truncate text-body font-semibold text-ink ${mono ? "font-mono" : "tabular"}`}
      >
        {value}
      </dd>
      {hint ? <p className="text-2xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="metric-label">{label}</dt>
      <dd className="mt-0.5 text-meta text-ink-body">{value}</dd>
    </div>
  );
}
