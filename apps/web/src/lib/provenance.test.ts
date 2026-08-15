import { describe, expect, test } from "vitest";

import { boxesForSpan, contextAround, findOccurrences } from "./provenance";
import type { PageWord } from "./api/types";

const PAGE = "L5-S1 disc extrusion\nIMPRESSION\nL5-S1 disc extrusion";

const WORDS: PageWord[] = [
  { text: "L5-S1", start: 0, end: 5, bbox: { x: 0.1, y: 0.1, width: 0.07, height: 0.02 } },
  { text: "disc", start: 6, end: 10, bbox: { x: 0.18, y: 0.1, width: 0.05, height: 0.02 } },
  { text: "extrusion", start: 11, end: 20, bbox: { x: 0.24, y: 0.1, width: 0.09, height: 0.02 } },
  { text: "IMPRESSION", start: 21, end: 31, bbox: { x: 0.1, y: 0.14, width: 0.14, height: 0.02 } },
];

describe("finding a passage on a page", () => {
  test("reports every occurrence in reading order", () => {
    const spans = findOccurrences(PAGE, "L5-S1 disc extrusion");

    expect(spans).toHaveLength(2);
    expect(PAGE.slice(spans[0].start, spans[0].end)).toBe("L5-S1 disc extrusion");
    expect(spans[1].start).toBeGreaterThan(spans[0].start);
  });

  test("returns nothing for a passage the page does not contain", () => {
    expect(findOccurrences(PAGE, "cervical fracture")).toEqual([]);
  });

  test("labels an occurrence with the words around it", () => {
    const [, second] = findOccurrences(PAGE, "L5-S1 disc extrusion");
    expect(contextAround(PAGE, second)).toContain("IMPRESSION");
  });
});

describe("previewing the region a span covers", () => {
  test("groups the words of one line into a single rectangle", () => {
    const boxes = boxesForSpan(WORDS, { start: 6, end: 20 });

    expect(boxes).toHaveLength(1);
    expect(boxes[0].x).toBeCloseTo(0.18);
    expect(boxes[0].width).toBeCloseTo(0.24 + 0.09 - 0.18);
  });

  test("gives a span that wraps one rectangle per line", () => {
    expect(boxesForSpan(WORDS, { start: 0, end: 31 })).toHaveLength(2);
  });

  test("has nothing to draw when the page carries no words", () => {
    expect(boxesForSpan([], { start: 0, end: 10 })).toEqual([]);
  });
});
