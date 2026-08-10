"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Accessible confirmation dialog: focus-trapped enough for a review workflow,
 *  closes on Escape, and labels itself for screen readers. */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Held in a ref so a caller passing an inline arrow does not re-run the
  // effect on every render — that would steal focus back from whatever input
  // the user is typing into after each keystroke.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink/30"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative z-10 w-full max-w-lg rounded-md border border-line bg-white shadow-lg outline-none"
      >
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-body font-semibold text-ink">{title}</h2>
          {description ? <div className="mt-1 text-body text-ink-muted">{description}</div> : null}
        </div>
        {children ? <div className="px-4 py-3">{children}</div> : null}
        <div className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3">
          {footer}
        </div>
      </div>
    </div>
  );
}
