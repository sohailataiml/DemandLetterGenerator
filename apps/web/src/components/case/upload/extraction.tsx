"use client";

/**
 * Running extraction, and watching it happen.
 *
 * The action posts to the existing async endpoint — 202 and a job id — and then
 * follows `/v1/jobs/{id}/events`. A polled query on the job row runs alongside
 * the stream, so if the stream drops the outcome is still observed; the stream
 * only makes the intermediate stages visible sooner.
 *
 * Nothing here decides anything. Extraction produces PROPOSED facts and stops;
 * an attorney is what turns one into evidence.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { streamJobEvents } from "@/lib/api/client";
import { queryKeys, useDocuments, useFacts, useJob, useStartExtraction } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { Badge, Button, Note, Panel, PanelHeader } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import type { TabKey } from "../workspace";

/**
 * Attorney wording for the stage names the pipeline emits.
 *
 * Only stages the backend actually reports are ever rendered. It would be easy
 * to draw a longer checklist here — "resolving source spans", "validating
 * provenance" — and tick the boxes off on a timer, but those would be pictures
 * of work rather than reports of it. An unrecognised stage falls through to its
 * raw name, which is honest and self-correcting when the pipeline gains a step.
 */
const STAGE_LABELS: Record<string, string> = {
  extracting: "Reading documents and proposing facts",
  resolving_verified_context: "Loading verified facts",
  drafting_sections: "Drafting sections",
  validating_claims: "Checking claims against the evidence",
  validating_financials: "Checking the arithmetic",
  binding_template: "Writing into the template",
  validating_template_fidelity: "Proving the template is unchanged",
  creating_artifact: "Building the document",
};

function labelFor(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ");
}

interface StreamedStage {
  stage: string;
  status: string;
  detail?: string;
}

export function ExtractionPanel({
  caseId,
  goToTab,
}: {
  caseId: string;
  goToTab: (tab: TabKey) => void;
}) {
  const documentsQuery = useDocuments(caseId);
  const factsQuery = useFacts(caseId);
  const startExtraction = useStartExtraction(caseId);
  const queryClient = useQueryClient();
  const toast = useToast();

  const [jobId, setJobId] = useState<string | null>(null);
  const [stages, setStages] = useState<StreamedStage[]>([]);
  const [summary, setSummary] = useState<{ proposed: number; documents: number } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The stream's "done" frame and the polled job row report the same outcome
  // and can arrive in either order. Whichever lands first settles the run; the
  // other is ignored rather than raising a second toast for one job.
  const settledRef = useRef<string | null>(null);

  // The polled job row is the safety net: the outcome comes from here even if
  // the event stream never connects.
  const jobQuery = useJob(jobId);

  useEffect(() => () => abortRef.current?.abort(), []);

  const documents = documentsQuery.data ?? [];
  const readable = documents.filter(
    (document) => String(document.status).toLowerCase() === "extracted",
  );
  const facts = factsQuery.data ?? [];
  const proposedCount = facts.filter((fact) => fact.status === "PROPOSED").length;
  const running = Boolean(jobId) && jobQuery.data?.status !== "COMPLETED" &&
    jobQuery.data?.status !== "FAILED";

  const finish = useCallback(
    (
      id: string,
      result: Record<string, unknown> | null | undefined,
      error: string | null | undefined,
    ) => {
      if (settledRef.current === id) return;
      settledRef.current = id;
      queryClient.invalidateQueries({ queryKey: ["case", caseId] });
      if (error) {
        setFailure(error);
        toast.push({ tone: "error", title: "Extraction failed", description: error });
        return;
      }
      const proposed = Number(result?.proposed ?? 0);
      const documentCount = Number(result?.documents ?? 0);
      setSummary({ proposed, documents: documentCount });
      toast.push({
        tone: "success",
        title: `${proposed} proposed fact${proposed === 1 ? "" : "s"} found`,
        description: "Each one needs attorney review before it can be used.",
      });
    },
    [caseId, queryClient, toast],
  );

  // The polled row settles the job even when no stream event arrived.
  useEffect(() => {
    const job = jobQuery.data;
    if (!job || !jobId) return;
    if (job.status === "COMPLETED") finish(jobId, job.result, null);
    else if (job.status === "FAILED") finish(jobId, null, job.error ?? "The job failed.");
  }, [finish, jobId, jobQuery.data]);

  const run = () => {
    setStages([]);
    setSummary(null);
    setFailure(null);
    settledRef.current = null;
    // Drop the previous job before asking for a new one, so its cached
    // COMPLETED row cannot momentarily re-report last run's numbers.
    setJobId(null);
    startExtraction.mutate(
      {},
      {
        onSuccess: (job) => {
          setJobId(job.id);
          abortRef.current?.abort();
          const controller = new AbortController();
          abortRef.current = controller;
          void streamJobEvents(
            job.id,
            {
              onStage: (stage) => setStages((current) => [...current, stage]),
              onDone: (payload) => {
                queryClient.invalidateQueries({ queryKey: queryKeys.job(job.id) });
                if (payload.status === "FAILED") {
                  finish(job.id, null, payload.error ?? "The job failed.");
                } else {
                  finish(job.id, payload.result, null);
                }
              },
            },
            controller.signal,
          ).catch(() => {
            // The polled job query above still reports the outcome; a dropped
            // stream costs progress detail, not correctness.
          });
        },
        onError: (error) =>
          toast.push({
            tone: "error",
            title: "Could not start extraction",
            description: error.message,
          }),
      },
    );
  };

  // Later reports of the same stage win, so "running" settles to "completed".
  const emitted = new Map<string, StreamedStage>();
  for (const stage of stages) emitted.set(stage.stage, stage);
  const timeline = [...emitted.values()];

  if (documents.length === 0) {
    return (
      <Panel>
        <PanelHeader
          title="Extract proposed facts"
          description="Available once case materials are on file."
        />
        <div className="px-4 py-3">
          <Note>
            Upload the evidence first. Extraction reads the documents above and proposes facts —
            it cannot invent one without a passage to cite.
          </Note>
        </div>
      </Panel>
    );
  }

  return (
    <Panel>
      <PanelHeader
        title="Extract proposed facts"
        description="Reads the case materials and proposes facts, each with a document, a page and character offsets into it."
        actions={
          <Button
            variant="primary"
            size="sm"
            disabled={running || startExtraction.isPending || readable.length === 0}
            onClick={run}
          >
            {running || startExtraction.isPending
              ? "Extracting…"
              : proposedCount > 0
                ? "Extract again"
                : "Extract proposed facts"}
          </Button>
        }
      />

      {readable.length === 0 ? (
        <div className="px-4 py-3">
          <Note>
            None of the uploaded documents has readable text. A scanned PDF has to be OCR'd before
            anything can be extracted from it.
          </Note>
        </div>
      ) : null}

      {jobId ? (
        <ol
          aria-live="polite"
          data-testid="extraction-progress"
          className="divide-y divide-line-soft border-t border-line-soft"
        >
          <li className="flex items-center gap-2.5 px-4 py-2">
            <StepMark status={timeline.length > 0 ? "completed" : "running"} />
            <span className="text-meta text-ink-body">Queued</span>
          </li>
          {timeline.map((stage) => (
            <li key={stage.stage} className="flex items-center gap-2.5 px-4 py-2">
              <StepMark status={stage.status} />
              <span
                className={cn(
                  "text-meta",
                  stage.status === "completed"
                    ? "text-ink-body"
                    : stage.status === "failed"
                      ? "text-stop-700"
                      : "font-medium text-ink",
                )}
              >
                {labelFor(stage.stage)}
              </span>
              {stage.detail ? (
                <span className="ml-auto truncate text-2xs text-ink-faint">{stage.detail}</span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}

      {failure ? (
        <div
          role="alert"
          className="border-t border-stop-200 bg-stop-50 px-4 py-3"
          data-testid="extraction-failure"
        >
          <p className="text-body font-medium text-stop-800">Extraction failed</p>
          <p className="mt-1 text-meta text-stop-700">{failure}</p>
          <Button size="sm" className="mt-2" onClick={run}>
            Try again
          </Button>
        </div>
      ) : null}

      {summary && !failure ? (
        <div
          className="border-t border-ok-200 bg-ok-50 px-4 py-3"
          data-testid="extraction-complete"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-body font-medium text-ok-700">Extraction complete</p>
              <p className="mt-0.5 text-meta text-ink-body">
                {summary.proposed} proposed fact{summary.proposed === 1 ? "" : "s"} from{" "}
                {summary.documents} document{summary.documents === 1 ? "" : "s"}.
              </p>
            </div>
            <Button variant="primary" size="sm" onClick={() => goToTab("facts")}>
              Review proposed facts
            </Button>
          </div>
        </div>
      ) : null}

      {!jobId && proposedCount > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-soft px-4 py-3">
          <p className="text-meta text-ink-body">
            <Badge tone="warning" strong>
              {proposedCount} awaiting review
            </Badge>{" "}
            Proposed facts cannot be used in the letter until an attorney verifies them.
          </p>
          <Button size="sm" onClick={() => goToTab("facts")}>
            Review proposed facts
          </Button>
        </div>
      ) : null}
    </Panel>
  );
}

function StepMark({ status }: { status: string | undefined }) {
  const glyph =
    status === "completed" ? "✓" : status === "failed" ? "✗" : status === "running" ? "●" : "○";
  const tone =
    status === "completed"
      ? "text-ok-700"
      : status === "failed"
        ? "text-stop-700"
        : status === "running"
          ? "text-accent-700"
          : "text-ink-faint";
  return (
    <span aria-hidden className={cn("w-3 text-center text-meta", tone)}>
      {glyph}
    </span>
  );
}
