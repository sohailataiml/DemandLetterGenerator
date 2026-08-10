"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { FactStatus, Severity } from "@/lib/api/types";

// ------------------------------------------------------------------ surfaces

export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "aside";
}) {
  return <Tag className={cn("card", className)}>{children}</Tag>;
}

export function PanelHeader({
  title,
  description,
  actions,
  dense = false,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  dense?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-line-soft px-4",
        dense ? "py-2.5" : "py-3",
      )}
    >
      <div className="min-w-0">
        <h2 className="card-title">{title}</h2>
        {description ? <p className="mt-0.5 text-meta text-ink-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function SectionHeading({ children }: { children: ReactNode }) {
  return <h3 className="eyebrow">{children}</h3>;
}

/** Label/value pair used across the read-only detail views. */
export function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="metric-label">{label}</dt>
      <dd className="mt-1 text-body text-ink">{children}</dd>
    </div>
  );
}

/** A headline figure: value dominates, label recedes. */
export function Metric({
  label,
  value,
  hint,
  tone = "default",
  size = "md",
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "ok" | "warn" | "stop" | "muted";
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const toneClass = {
    default: "text-ink",
    ok: "text-ok-700",
    warn: "text-warn-700",
    stop: "text-stop-700",
    muted: "text-ink-muted",
  }[tone];

  return (
    <div className={cn("min-w-0", className)}>
      <p className="metric-label">{label}</p>
      <p
        className={cn(
          "tabular mt-1 font-semibold tracking-tight",
          size === "lg" ? "text-metric-lg" : size === "sm" ? "text-[1.0625rem]" : "text-metric",
          toneClass,
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-2xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

// -------------------------------------------------------------------- badges

const BADGE_TONES = {
  neutral: "bg-surface-sunken text-ink-muted ring-line-strong",
  accent: "bg-accent-50 text-accent-800 ring-accent-200",
  success: "bg-ok-50 text-ok-700 ring-ok-200",
  warning: "bg-warn-50 text-warn-700 ring-warn-200",
  danger: "bg-stop-50 text-stop-700 ring-stop-200",
  muted: "bg-surface-muted text-ink-faint ring-line",
} as const;

export type BadgeTone = keyof typeof BADGE_TONES;

export function Badge({
  children,
  tone = "neutral",
  className,
  title,
  strong = false,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
  title?: string;
  strong?: boolean;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded ring-1 ring-inset",
        strong
          ? "px-2 py-0.5 text-2xs font-semibold uppercase tracking-[0.07em]"
          : "px-1.5 py-0.5 text-2xs font-medium",
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const FACT_STATUS_TONE: Record<FactStatus, BadgeTone> = {
  VERIFIED: "success",
  PROPOSED: "warning",
  REJECTED: "danger",
  SUPERSEDED: "muted",
};

export function FactStatusBadge({ status }: { status: FactStatus }) {
  return (
    <Badge tone={FACT_STATUS_TONE[status]} strong>
      {status}
    </Badge>
  );
}

const SEVERITY_TONE: Record<Severity, BadgeTone> = {
  BLOCKING: "danger",
  WARNING: "warning",
  INFO: "neutral",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge tone={SEVERITY_TONE[severity]} strong>
      {severity}
    </Badge>
  );
}

// ------------------------------------------------------------------ controls

const BUTTON_VARIANTS = {
  primary:
    "bg-accent-700 text-white hover:bg-accent-800 focus-visible:outline-accent-700 disabled:bg-line-strong disabled:text-white",
  secondary:
    "bg-white text-ink-body ring-1 ring-inset ring-line-strong hover:bg-surface-muted hover:text-ink focus-visible:outline-accent-600 disabled:text-ink-faint",
  ghost:
    "bg-transparent text-ink-muted hover:bg-surface-sunken hover:text-ink focus-visible:outline-accent-600 disabled:text-ink-faint",
  danger:
    "bg-stop-600 text-white hover:bg-stop-700 focus-visible:outline-stop-600 disabled:bg-line-strong",
} as const;

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: "sm" | "md";
}) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors duration-150",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-meta" : "px-3 py-1.5 text-meta",
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}

/** Inline text link that reads as an affordance without a button's weight. */
export function LinkButton({
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "rounded text-meta font-medium text-accent-700 underline-offset-2 transition-colors hover:text-accent-800 hover:underline",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** Collapsed-by-default explanation. Native disclosure: keyboard accessible. */
export function Disclosure({
  summary,
  children,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={cn("group rounded border border-line bg-surface-muted", className)}>
      <summary className="cursor-pointer list-none px-3 py-2 text-meta font-medium text-ink-muted transition-colors hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="text-2xs text-ink-faint transition-transform duration-150 group-open:rotate-90"
          >
            ▸
          </span>
          {summary}
        </span>
      </summary>
      <div className="border-t border-line-soft px-3 py-2.5">{children}</div>
    </details>
  );
}

// ------------------------------------------------------------------- states

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("animate-pulse rounded bg-line-soft", className)}
    />
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5 p-4">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className={index === 0 ? "h-4 w-1/3" : "h-4 w-full"} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  compact = false,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cn("px-4 text-center", compact ? "py-6" : "py-10")}>
      <p className="text-body font-medium text-ink">{title}</p>
      {description ? (
        <div className="mx-auto mt-1.5 max-w-md text-meta leading-6 text-ink-muted">
          {description}
        </div>
      ) : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: { message: string; status?: number } | null;
  onRetry?: () => void;
}) {
  if (!error) return null;
  const isAuth = error.status === 401 || error.status === 403;
  return (
    <div role="alert" className="m-4 rounded border border-stop-200 bg-stop-50 px-4 py-3">
      <p className="text-body font-medium text-stop-800">
        {isAuth ? "Not permitted" : "Could not load this data"}
      </p>
      <p className="mt-1 text-meta text-stop-700">{error.message}</p>
      {isAuth ? (
        <p className="mt-1 text-2xs text-stop-600">
          The request used the role configured in NEXT_PUBLIC_USER_ROLE.
        </p>
      ) : null}
      {onRetry ? (
        <Button size="sm" className="mt-2.5" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/** Explanatory note attached to a figure or rule, kept visually quiet. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="text-meta leading-6 text-ink-muted">{children}</p>;
}
