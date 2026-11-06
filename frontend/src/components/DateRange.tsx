const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysAgo = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return ymd(d); };

export const RANGES: Record<string, () => [string, string]> = {
  "7": () => [daysAgo(6), ""],
  "30": () => [daysAgo(29), ""],
  "90": () => [daysAgo(89), ""],
  year: () => [`${new Date().getFullYear()}-01-01`, ""],
  all: () => ["", ""],
};

export type Range = { preset: string; from: string; to: string };
export const defaultRange = (preset = "30"): Range => { const [from, to] = RANGES[preset](); return { preset, from, to }; };

/** True when an ISO date/time falls inside the range (dates compared in local time). */
export function inRange(iso: string | null | undefined, r: Range): boolean {
  if (!iso) return false;
  const d = ymd(new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z"));
  return (!r.from || d >= r.from) && (!r.to || d <= r.to);
}

export function DateRangePicker({ value, onChange, testId }: { value: Range; onChange: (r: Range) => void; testId?: string }) {
  const pick = (preset: string) => {
    if (RANGES[preset]) { const [from, to] = RANGES[preset](); onChange({ preset, from, to }); }
    else onChange({ ...value, preset });
  };
  return (
    <>
      <select value={value.preset} onChange={(e) => pick(e.target.value)} aria-label="Date range" data-testid={testId}>
        <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option>
        <option value="year">This year</option><option value="all">All time</option><option value="custom">Custom dates</option>
      </select>
      <label className="row small">From <input type="date" value={value.from} onChange={(e) => onChange({ ...value, preset: "custom", from: e.target.value })} /></label>
      <label className="row small">To <input type="date" value={value.to} onChange={(e) => onChange({ ...value, preset: "custom", to: e.target.value })} /></label>
    </>
  );
}
