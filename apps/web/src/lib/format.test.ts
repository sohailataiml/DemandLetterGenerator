import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, formatMoneyRange, humanize } from "./format";

describe("money formatting", () => {
  it("groups an exact decimal string without going through a float", () => {
    expect(formatMoney("9980.00")).toBe("$9,980.00");
    expect(formatMoney("1234567.89")).toBe("$1,234,567.89");
    expect(formatMoney("0.00")).toBe("$0.00");
  });

  it("preserves cents that a float round-trip would disturb", () => {
    // 0.1 + 0.2 in binary floating point is 0.30000000000000004.
    expect(formatMoney("1000000000000.10")).toBe("$1,000,000,000,000.10");
    expect(formatMoney("8014.15")).toBe("$8,014.15");
  });

  it("renders an unknown amount as a placeholder, never as zero", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(null, "Pending")).toBe("Pending");
    expect(formatMoney(undefined)).toBe("—");
  });

  it("collapses a range when both ends match", () => {
    expect(formatMoneyRange("8400.00", "11200.00")).toBe("$8,400.00 – $11,200.00");
    expect(formatMoneyRange("4200.00", "4200.00")).toBe("$4,200.00");
  });
});

describe("date formatting", () => {
  it("renders a plain date without shifting it across time zones", () => {
    expect(formatDate("2025-07-06")).toBe("Jul 6, 2025");
    expect(formatDate("2026-01-01")).toBe("Jan 1, 2026");
  });

  it("falls back cleanly for missing values", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("humanize", () => {
  it("makes backend enum values readable", () => {
    expect(humanize("MRI_REPORT")).toBe("Mri Report");
    expect(humanize("follow_up")).toBe("Follow Up");
    expect(humanize(null)).toBe("—");
  });
});
