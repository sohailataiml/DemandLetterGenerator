"use client";

/**
 * What the AI boundary did to this draft.
 *
 * Two controls protect a demand letter and they are not the same thing, so this
 * panel never implies otherwise:
 *
 *   privacy    — what left this system, and what the gateway did to it before
 *                an external model saw it. That is what this card reports.
 *   provenance — whether a claim traces to a verified fact and an exact passage
 *                in an original document. That is the evidence rail's job.
 *
 * Everything rendered here is a count or a name that the backend already
 * received from the gateway's privacy summary. No detected value, no token, and
 * no mapping exists on this side of the wire to render even by accident.
 */

import { Badge, Note, SectionHeading } from "@/components/ui/primitives";
import type { GenerationMetadata } from "@/lib/api/types";

const BOUNDARY_LABEL: Record<string, string> = {
  secure_gateway: "Secure Gateway",
  direct_provider: "Direct provider",
  local: "Local drafter",
};

/** The numeric fields of the gateway's privacy summary, in reviewer order. */
type PrivacyCountKey =
  | "detected"
  | "tokenized"
  | "pseudonymized"
  | "redacted"
  | "restored"
  | "blocked";

const COUNT_ROWS: { key: PrivacyCountKey; label: string }[] = [
  { key: "detected", label: "Detected" },
  { key: "tokenized", label: "Tokenized" },
  { key: "pseudonymized", label: "Pseudonymized" },
  { key: "redacted", label: "Redacted" },
  { key: "restored", label: "Restored" },
  { key: "blocked", label: "Blocked" },
];

/**
 * What the provider was handed for this section, and what came back.
 *
 * The "sent" side is the gateway's own masked rendering — it replaces protected
 * values with `⟦TYPE:••••⟧` before it hands the preview over, so this panel can
 * never show a real value even if one were in the prompt. The "received" side is
 * the restored text, which is the section itself: the values are back precisely
 * because the reviewer is authorized to see them and the provider was not.
 */
function BoundaryTranscript({
  preview,
  restoredText,
}: {
  preview: NonNullable<GenerationMetadata["sections"]>[string]["protected_preview"];
  restoredText?: string;
}) {
  if (!preview?.text) return null;
  //: Whether the visible slice actually shows a masked value.
  const hasMask = preview.text.includes("⟦");
  return (
    <details className="mt-2 rounded border border-line bg-surface-muted" data-testid="boundary-transcript">
      <summary className="cursor-pointer px-2.5 py-1.5 text-2xs font-medium text-ink-muted">
        What the model actually saw
      </summary>
      <div className="space-y-2 border-t border-line-soft px-2.5 py-2">
        <div>
          <p className="eyebrow">Sent to the provider — protected</p>
          <pre
            data-testid="protected-sent"
            className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2 text-2xs leading-4 text-ink-body"
          >
            {preview.text}
          </pre>
          {preview.truncated ? (
            // Without this the panel reads as a contradiction: a summary saying
            // values were protected, above a slice of prompt containing none of
            // the ⟦TYPE:••••⟧ markers, because the gateway cut the preview
            // before them.
            <p className="mt-1 text-2xs leading-4 text-warn-800" data-testid="preview-truncated">
              The gateway truncated this preview at {preview.text.length} characters.
              {hasMask
                ? " The rest of the prompt is not shown."
                : " The protected values below appear later in the prompt, past the cut, so no ⟦TYPE:••••⟧ marker is visible here."}
            </p>
          ) : null}
          {preview.entity_summary && preview.entity_summary.length > 0 ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {preview.entity_summary.map((entry) => (
                <Badge key={`${entry.entity_type}-${entry.action}`} tone="neutral">
                  {entry.entity_type.toLowerCase().replace(/_/g, " ")} · {entry.action} ·{" "}
                  {entry.count}
                </Badge>
              ))}
            </div>
          ) : null}
          <p className="mt-1 text-2xs text-ink-faint">
            Outbound scan: {preview.outbound_scan ?? "not reported"}
          </p>
        </div>

        {restoredText ? (
          <div>
            <p className="eyebrow">Returned and restored</p>
            <pre
              data-testid="restored-received"
              className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2 text-2xs leading-4 text-ink-body"
            >
              {restoredText}
            </pre>
            <p className="mt-1 text-2xs text-ink-faint">
              Authorized values were put back by the gateway after the provider replied.
            </p>
          </div>
        ) : null}
      </div>
    </details>
  );
}

export function AiPrivacyCard({
  metadata,
  sectionKey,
  restoredText,
}: {
  metadata: GenerationMetadata | null | undefined;
  /** Which section's boundary record to expand, when one was recorded. */
  sectionKey?: string;
  /** The restored prose for that section — the other half of the transcript. */
  restoredText?: string;
}) {
  if (!metadata) {
    // A demand drafted before this was recorded, or not drafted at all. Saying
    // nothing is better than showing zeros that look like a clean bill.
    return null;
  }

  const boundary = metadata.ai_boundary;
  const privacy = metadata.privacy ?? {};
  const rows = COUNT_ROWS.filter((row) => typeof privacy[row.key] === "number");

  return (
    <div data-testid="ai-privacy">
      <SectionHeading>AI privacy</SectionHeading>
      <div className="mt-1.5 rounded border border-line bg-white px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {boundary === "secure_gateway" ? (
            <Badge tone="success" strong>
              ✓ Secure Gateway
            </Badge>
          ) : boundary === "direct_provider" ? (
            <Badge tone="warning" strong>
              Direct provider
            </Badge>
          ) : (
            <Badge tone="muted" strong>
              {BOUNDARY_LABEL[boundary] ?? boundary}
            </Badge>
          )}
          {metadata.upstream_model ? (
            <Badge tone="muted">{metadata.upstream_model}</Badge>
          ) : null}
        </div>

        {boundary === "secure_gateway" ? (
          <p className="mt-1.5 text-2xs leading-4 text-ink-faint">
            Prompts crossed the secure gateway&apos;s privacy pipeline before any external
            model saw them. Counts are what the gateway reported; no sensitive value is
            stored or shown here.
          </p>
        ) : boundary === "direct_provider" ? (
          <p className="mt-1.5 text-2xs leading-4 text-warn-800">
            This draft was sent straight to the model vendor, bypassing the privacy
            gateway.
          </p>
        ) : (
          <p className="mt-1.5 text-2xs leading-4 text-ink-faint">
            Drafted locally from verified facts. Nothing left this system.
          </p>
        )}

        {rows.length > 0 ? (
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            {rows.map((row) => (
              <div key={row.key} className="flex items-baseline justify-between gap-2">
                <dt className="text-2xs text-ink-muted">{row.label}</dt>
                <dd
                  data-testid={`privacy-${row.key}`}
                  className="tabular text-meta font-medium text-ink"
                >
                  {privacy[row.key]}
                </dd>
              </div>
            ))}
          </dl>
        ) : boundary === "secure_gateway" ? (
          <Note>The gateway reported no privacy summary for this run.</Note>
        ) : null}

        {privacy.entity_types && Object.keys(privacy.entity_types).length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(privacy.entity_types).map(([entity, count]) => (
              // The entity *type* and how many of them — never the value.
              <Badge key={entity} tone="neutral">
                {entity.toLowerCase().replace(/_/g, " ")} · {count}
              </Badge>
            ))}
          </div>
        ) : null}

        {boundary === "secure_gateway" && sectionKey ? (
          <BoundaryTranscript
            preview={metadata.sections?.[sectionKey]?.protected_preview}
            restoredText={restoredText}
          />
        ) : null}
      </div>
    </div>
  );
}
