/** Dashboard time period: last 30/60/90 days, year to date, a full calendar year, or all time. */
const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fmt = (s: string) =>
  new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export type PeriodPreset = "30" | "60" | "90" | "ytd" | "year" | "all";
export type Period = { preset: PeriodPreset; year: number };

export const PERIOD_KEY = "funnelhub.dashboardPeriod";
export function loadPeriod(): Period {
  try {
    const p = JSON.parse(localStorage.getItem(PERIOD_KEY) || "null");
    if (p && ["30", "60", "90", "ytd", "year", "all"].includes(p.preset)) return { preset: p.preset, year: Number(p.year) || new Date().getFullYear() };
  } catch { /* ignore */ }
  return { preset: "30", year: new Date().getFullYear() };
}
export const savePeriod = (p: Period) => localStorage.setItem(PERIOD_KEY, JSON.stringify(p));

/** start/end are local YYYY-MM-DD dates sent to the API ("" = open-ended). */
export function periodInfo(p: Period): { start: string; end: string; label: string; short: string; range: string } {
  const today = new Date();
  const back = (n: number) => { const d = new Date(); d.setDate(d.getDate() - (n - 1)); return ymd(d); };
  let start = "", end = ymd(today), label = "", short = "";
  switch (p.preset) {
    case "30": case "60": case "90":
      start = back(Number(p.preset)); label = `Last ${p.preset} days`; short = `${p.preset} days`; break;
    case "ytd":
      start = `${today.getFullYear()}-01-01`; label = `Year to date (${today.getFullYear()})`; short = "year to date"; break;
    case "year": {
      start = `${p.year}-01-01`;
      const last = `${p.year}-12-31`;
      end = last < end ? last : end;
      label = p.year === today.getFullYear() ? `Full year ${p.year} (so far)` : `Full year ${p.year}`;
      short = String(p.year); break;
    }
    default:
      label = "All time"; short = "all time"; end = "";
  }
  const range = start ? `${fmt(start)} – ${end ? fmt(end) : "today"}` : "Everything in the CRM";
  return { start, end, label, short, range };
}

/** Minutes to add to UTC to get local time (Central time = -360 or -300). */
export const tzOffset = () => -new Date().getTimezoneOffset();

export function PeriodPicker({ value, onChange, testId }: { value: Period; onChange: (p: Period) => void; testId?: string }) {
  const thisYear = new Date().getFullYear();
  const years = Array.from({ length: 8 }, (_, i) => thisYear - i);
  return (
    <div className="row period-picker">
      <select aria-label="Time period" data-testid={testId} value={value.preset}
        onChange={(e) => onChange({ ...value, preset: e.target.value as PeriodPreset })}>
        <option value="30">Last 30 days</option>
        <option value="60">Last 60 days</option>
        <option value="90">Last 90 days</option>
        <option value="ytd">Year to date</option>
        <option value="year">Full year…</option>
        <option value="all">All time</option>
      </select>
      {value.preset === "year" && (
        <select aria-label="Year" value={value.year} onChange={(e) => onChange({ ...value, year: Number(e.target.value) })}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      )}
    </div>
  );
}
