"use client";

import { Disclosure } from "@/components/ui/primitives";

/**
 * The guarantees the system makes, available on demand rather than occupying
 * the workspace permanently.
 */
export function SafeguardsDisclosure({ className }: { className?: string }) {
  return (
    <Disclosure summary="How safeguards work" className={className}>
      <ul className="space-y-1.5 text-2xs leading-5 text-ink-muted">
        <li>Facts are proposed, then verified by a person — nothing verifies itself.</li>
        <li>Verified facts are immutable; a correction supersedes the original.</li>
        <li>Every total is computed by the backend, never by the drafting model.</li>
        <li>
          Amounts and dates in generated prose must exist in the case data, or validation blocks
          approval.
        </li>
        <li>The backend re-runs validation at the moment of approval, before locking bytes.</li>
      </ul>
    </Disclosure>
  );
}
