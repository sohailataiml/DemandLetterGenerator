/**
 * Client-side helpers for showing — never for deciding — where evidence sits.
 *
 * The backend owns provenance: it decides whether a citation is exact, and it
 * computes the rectangles that get stored. Everything here is for the picker
 * that lets a reviewer settle an ambiguous citation: it finds the places a
 * passage occurs on a page and previews the region each one covers. Whatever
 * the reviewer chooses is sent back as offsets and re-derived server-side, so a
 * disagreement between this preview and the stored citation can only ever cost
 * a redraw, never a wrong record.
 */

import type { BoundingBox, PageWord } from "./api/types";

export interface TextSpan {
  start: number;
  end: number;
}

/** Every place `quote` appears verbatim in `text`, in reading order. */
export function findOccurrences(text: string, quote: string): TextSpan[] {
  const needle = quote.trim();
  if (!text || needle.length === 0) return [];

  const spans: TextSpan[] = [];
  let from = 0;
  for (;;) {
    const index = text.indexOf(needle, from);
    if (index === -1) break;
    spans.push({ start: index, end: index + needle.length });
    from = index + Math.max(1, needle.length);
  }
  return spans;
}

/** A short window of page text around a span, for labelling an occurrence. */
export function contextAround(text: string, span: TextSpan, padding = 40): string {
  const before = text.slice(Math.max(0, span.start - padding), span.start);
  const after = text.slice(span.end, Math.min(text.length, span.end + padding));
  return `…${before}${text.slice(span.start, span.end)}${after}…`.replace(/\s+/g, " ");
}

/** Two words are on the same visual line when their vertical centres agree. */
function sameLine(previous: PageWord, current: PageWord): boolean {
  const previousCentre = previous.bbox.y + previous.bbox.height / 2;
  const currentCentre = current.bbox.y + current.bbox.height / 2;
  const tolerance = 0.6 * Math.max(previous.bbox.height, current.bbox.height, 1e-6);
  return Math.abs(previousCentre - currentCentre) <= tolerance;
}

function union(a: BoundingBox, b: BoundingBox): BoundingBox {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return {
    x,
    y,
    width: Math.max(a.x + a.width, b.x + b.width) - x,
    height: Math.max(a.y + a.height, b.y + b.height) - y,
  };
}

/**
 * Preview rectangles for a span — one per visual line, mirroring the rule the
 * backend applies when it stores them.
 */
export function boxesForSpan(words: PageWord[], span: TextSpan): BoundingBox[] {
  const covered = words.filter((word) => word.start < span.end && word.end > span.start);
  if (covered.length === 0) return [];

  const lines: BoundingBox[] = [];
  let current: BoundingBox | null = null;
  let previous: PageWord | null = null;

  for (const word of covered) {
    if (current === null || previous === null || !sameLine(previous, word)) {
      if (current) lines.push(current);
      current = word.bbox;
    } else {
      current = union(current, word.bbox);
    }
    previous = word;
  }
  if (current) lines.push(current);
  return lines;
}
