/**
 * Display formatting.
 *
 * Money never passes through a JavaScript number: the backend sends exact
 * decimal strings and these helpers group digits with string operations only.
 * Parsing "9980.00" into a float to re-render it would reintroduce exactly the
 * class of error the backend's Decimal arithmetic exists to prevent.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** Group the integer part of a decimal string: "9980.00" → "9,980.00". */
function groupDigits(value: string): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = "00"] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const cents = (fraction + "00").slice(0, 2);
  return `${negative ? "-" : ""}${grouped}.${cents}`;
}

export function formatMoney(value: string | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value; // already formatted upstream
  return `$${groupDigits(value)}`;
}

/** A money range, collapsed when both ends match. */
export function formatMoneyRange(low: string, high: string): string {
  return low === high ? formatMoney(low) : `${formatMoney(low)} – ${formatMoney(high)}`;
}

/** "2025-07-06" → "Jul 6, 2025". Parsed as a plain date, never shifted by zone. */
export function formatDate(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${MONTHS[Number(month) - 1]} ${Number(day)}, ${year}`;
}

export function formatDateLong(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${MONTHS_LONG[Number(month) - 1]} ${Number(day)}, ${year}`;
}

/**
 * Timestamps are UTC. The backend writes tz-aware UTC values; SQLite hands some
 * of them back without an offset, so a bare timestamp is read as UTC rather
 * than silently reinterpreted in the viewer's zone.
 */
function toDate(value: string): Date {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function formatDateTime(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
  const hours = date.getHours() % 12 || 12;
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const meridiem = date.getHours() < 12 ? "AM" : "PM";
  return `${day} at ${hours}:${minutes} ${meridiem}`;
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(value);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "MRI_REPORT" → "MRI Report"; "follow_up" → "Follow up". */
export function humanize(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced
    .split(" ")
    .map((word) =>
      word.length > 1 && word === word.toUpperCase()
        ? word.charAt(0) + word.slice(1).toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}

export function shortHash(value: string | null | undefined): string {
  if (!value) return "—";
  return `${value.slice(0, 12)}…`;
}
