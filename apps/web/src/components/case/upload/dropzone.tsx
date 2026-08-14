"use client";

/**
 * Drag-and-drop plus a native file picker, in one accessible control.
 *
 * The drop area is a real `<button>` wrapping a hidden `<input type="file">`,
 * so Tab reaches it, Enter and Space open the picker, and a screen reader
 * announces something other than a `<div>`. Everything drag does, the picker
 * does too — dragging is never the only way to add a file.
 */

import { useRef, useState } from "react";

import { cn } from "@/lib/cn";

export interface DropzoneProps {
  id: string;
  label: string;
  hint: string;
  buttonLabel: string;
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  busy?: boolean;
  onFiles: (files: File[]) => void;
}

export function Dropzone({
  id,
  label,
  hint,
  buttonLabel,
  accept,
  multiple = false,
  disabled = false,
  busy = false,
  onFiles,
}: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const accepted = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    onFiles(Array.from(files));
  };

  return (
    <div className="px-4 py-3">
      <button
        type="button"
        aria-describedby={`${id}-hint`}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          if (disabled) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          if (disabled) return;
          event.preventDefault();
          setDragging(false);
          accepted(event.dataTransfer.files);
        }}
        className={cn(
          "flex w-full flex-col items-center gap-1.5 rounded border border-dashed px-4 py-7 text-center transition-colors duration-150",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
          disabled
            ? "cursor-not-allowed border-line bg-surface-muted"
            : dragging
              ? "border-accent-500 bg-accent-50"
              : "border-line-strong bg-surface-muted hover:border-accent-400 hover:bg-accent-50/40",
        )}
      >
        <span className="text-body font-medium text-ink">{label}</span>
        <span id={`${id}-hint`} className="text-meta text-ink-muted">
          {hint}
        </span>
        <span
          className={cn(
            "mt-2 inline-flex items-center rounded px-3 py-1.5 text-meta font-medium",
            disabled ? "bg-line-strong text-white" : "bg-accent-700 text-white",
          )}
        >
          {busy ? "Uploading…" : buttonLabel}
        </span>
      </button>

      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        aria-label={label}
        onChange={(event) => {
          accepted(event.target.files);
          // Reset so choosing the same file twice still fires a change event.
          event.target.value = "";
        }}
      />
    </div>
  );
}
