"use client";

/**
 * What is still missing before this case can produce a demand.
 *
 * Every line is derived from data the backend returned — templates, documents,
 * facts, the demand row. Nothing here is a rule of its own: the last step
 * reports the server's blocking-issue count rather than deciding readiness, so
 * this panel can never disagree with the endpoint that actually approves.
 */

import { Badge, Panel, PanelHeader } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import type { Demand, Fact, LetterTemplate, SourceDocument } from "@/lib/api/types";

export type StepState = "done" | "attention" | "todo";

export interface SetupStep {
  label: string;
  detail: string;
  state: StepState;
}

const MARK: Record<StepState, string> = { done: "✓", attention: "●", todo: "○" };

const MARK_TONE: Record<StepState, string> = {
  done: "text-ok-700",
  attention: "text-warn-700",
  todo: "text-ink-faint",
};

export function buildSetupSteps(
  templates: LetterTemplate[],
  documents: SourceDocument[],
  facts: Fact[],
  demand: Demand | null,
): SetupStep[] {
  const proposed = facts.filter((fact) => fact.status === "PROPOSED").length;
  const verified = facts.filter((fact) => fact.status === "VERIFIED").length;

  const steps: SetupStep[] = [
    templates.length > 0
      ? {
          label: "Demand template",
          detail: templates[0].original_filename,
          state: "done",
        }
      : {
          label: "Demand template required",
          detail: "Upload the attorney's Word document",
          state: "todo",
        },
    documents.length > 0
      ? {
          label: "Case materials",
          detail: `${documents.length} document${documents.length === 1 ? "" : "s"} on file`,
          state: "done",
        }
      : {
          label: "Case materials required",
          detail: "Upload the evidence this demand rests on",
          state: "todo",
        },
  ];

  if (facts.length === 0) {
    steps.push({
      label: "Facts not extracted",
      detail:
        documents.length > 0
          ? "Run extraction on the uploaded materials"
          : "Waiting for documents",
      state: "todo",
    });
  } else if (proposed > 0) {
    steps.push({
      label: `${proposed} proposed fact${proposed === 1 ? " requires" : "s require"} review`,
      detail: `${verified} already verified`,
      state: "attention",
    });
  } else {
    steps.push({
      label: `${verified} verified fact${verified === 1 ? "" : "s"}`,
      detail: "Nothing awaiting review",
      state: "done",
    });
  }

  if (!demand) {
    steps.push({ label: "Demand not drafted", detail: "No draft created yet", state: "todo" });
  } else if (demand.locked) {
    steps.push({
      label: "Demand approved",
      detail: `Version ${demand.version}, locked`,
      state: "done",
    });
  } else {
    const blocking = demand.issues.filter((issue) => issue.severity === "BLOCKING").length;
    steps.push(
      blocking > 0
        ? {
            label: `${blocking} blocking issue${blocking === 1 ? "" : "s"}`,
            detail: "The server refuses approval while these stand",
            state: "attention",
          }
        : {
            label: `Demand drafted · version ${demand.version}`,
            detail: demand.generated_at ? "No blocking issues recorded" : "Not generated yet",
            state: demand.generated_at ? "done" : "attention",
          },
    );
  }

  return steps;
}

export function CaseSetup({
  templates,
  documents,
  facts,
  demand,
}: {
  templates: LetterTemplate[];
  documents: SourceDocument[];
  facts: Fact[];
  demand: Demand | null;
}) {
  const steps = buildSetupSteps(templates, documents, facts, demand);
  const outstanding = steps.filter((step) => step.state !== "done").length;

  return (
    <Panel>
      <PanelHeader
        title="Case setup"
        dense
        actions={
          <Badge tone={outstanding === 0 ? "success" : "warning"} strong>
            {outstanding === 0 ? "Complete" : `${outstanding} outstanding`}
          </Badge>
        }
      />
      <ol className="flex flex-wrap gap-x-6 gap-y-1.5 px-4 py-2.5">
        {steps.map((step) => (
          <li
            key={step.label}
            data-testid={`setup-${step.state}`}
            className="flex min-w-0 items-baseline gap-1.5"
          >
            <span aria-hidden className={cn("text-meta", MARK_TONE[step.state])}>
              {MARK[step.state]}
            </span>
            <span className="truncate text-meta text-ink-body">{step.label}</span>
            <span className="truncate text-2xs text-ink-faint">{step.detail}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
