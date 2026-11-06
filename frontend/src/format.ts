export const money = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const num = (n: number | null | undefined) => (n ?? 0).toLocaleString();
export const pct = (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${n}%`);

/** API datetimes are naive UTC; treat them as UTC for display. */
export const parseUtc = (s: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
export const dateTime = (s: string | null | undefined) =>
  s ? parseUtc(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
export const dateOnly = (s: string | null | undefined) =>
  s ? new Date(s.length === 10 ? `${s}T12:00:00` : parseUtc(s)).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";

/** Convert API UTC string -> value for <input type="datetime-local"> (local time). */
export const toLocalInput = (s: string | null | undefined) => {
  if (!s) return "";
  const d = parseUtc(s);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
/** Convert <input type="datetime-local"> value -> naive UTC ISO string for the API. */
export const fromLocalInput = (v: string) => (v ? new Date(v).toISOString().slice(0, 19) : null);

export const fullName = (c: { first_name: string; last_name: string }) => `${c.first_name} ${c.last_name}`.trim();
/** Money with cents, for orders and receipts. */
export const money2 = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
