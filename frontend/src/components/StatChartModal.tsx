import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { money, money2, num } from "../format";
import { toastError } from "../store/toastStore";
import { Period, PeriodPicker, periodInfo, tzOffset } from "./Period";
import { linearTrend, periodLabel, SeriesPoint, TrendChart } from "./TrendChart";

export type MetricKey = "won_revenue" | "open_pipeline" | "win_rate" | "contacts" | "new_contacts" | "audience" | "views" | "views_gained" | "views_total";

type Series = {
  metric: MetricKey; label: string; kind: "sum" | "state" | "rate"; format: "money" | "pct" | "num"; bucket: string;
  start: string; end: string; points: SeriesPoint[]; total: number | null; latest: number | null; note: string;
};

const EXPLAIN: Record<MetricKey, string> = {
  won_revenue: "Money from deals marked won, placed on the day each deal closed.",
  open_pipeline: "Total value of deals that were still open at the end of each period.",
  win_rate: "Of the deals closed in each period, the share that were won. Blank periods had no closed deals.",
  contacts: "How many contacts the CRM had at the end of each period.",
  new_contacts: "Contacts added in each period.",
  audience: "Followers and subscribers across your active channels, as saved by the CRM each day.",
  views: "Current views of the posts published in each period (an old video's views stay on the day it went up).",
  views_gained: "How many views all your channels gained in each period, from the lifetime totals the CRM saves each day.",
  views_total: "Lifetime views across your active channels at the end of each period, as saved by the CRM each day.",
};

const fmtFor = (f: Series["format"]) => (f === "money" ? (n: number) => money(n) : f === "pct" ? (n: number) => `${Math.round(n * 10) / 10}%` : (n: number) => num(Math.round(n)));
const unit = (b: string) => (b === "day" ? "day" : b === "week" ? "week" : "month");

export default function StatChartModal({ metric: initialMetric, period: initialPeriod, onClose }: {
  metric: MetricKey; period: Period; onClose: () => void;
}) {
  const [metric, setMetric] = useState<MetricKey>(initialMetric);
  const [period, setPeriod] = useState<Period>(initialPeriod);
  const [bucket, setBucket] = useState("auto");
  const [running, setRunning] = useState(false);
  const [showTrend, setShowTrend] = useState(true);
  const [data, setData] = useState<Series | null>(null);
  const [loading, setLoading] = useState(true);
  const info = periodInfo(period);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose]);

  useEffect(() => {
    setLoading(true);
    api.get<Series>(`/dashboard/series/${metric}`, { start: info.start, end: info.end, bucket, tz_offset: tzOffset() })
      .then(setData).catch(toastError).finally(() => setLoading(false));
  }, [metric, info.start, info.end, bucket]);

  const canRun = data?.kind === "sum";
  const points = useMemo(() => {
    if (!data) return [];
    if (!(canRun && running)) return data.points;
    let acc = 0;
    return data.points.map((p) => ({ ...p, value: (acc += p.value ?? 0) }));
  }, [data, running, canRun]);

  const format = data ? fmtFor(data.format) : num;
  const trend = linearTrend(points.map((p) => p.value));
  const known = points.filter((p) => p.value !== null);
  const raw = (data?.points ?? []).filter((p) => p.value !== null) as { value: number; start: string; end: string }[];
  const avg = raw.length ? raw.reduce((s, p) => s + p.value, 0) / raw.length : null;   // from real per-period values
  const best = raw.length ? raw.reduce((a, b) => (b.value > a.value ? b : a)) : null;
  const vals = points.map((p) => p.value);
  const firstI = vals.findIndex((v) => v !== null);
  const lastI = vals.length - 1 - [...vals].reverse().findIndex((v) => v !== null);
  const trendStart = trend?.at(firstI), trendEnd = trend?.at(lastI);
  // % change only makes sense when the line starts clearly above zero
  const trendPct = trend && trendStart !== undefined && trendEnd !== undefined && trendStart > Math.abs(trendEnd) * 0.05
    ? ((trendEnd - trendStart) / trendStart) * 100 : null;
  const slopeText = (v: number) => {
    const a = Math.abs(v);
    if (data?.format === "pct") return `${Math.round(a * 10) / 10} pts`;
    if (data?.format === "money") return a < 10 ? money2(a) : money(a);
    return a < 10 ? a.toLocaleString(undefined, { maximumFractionDigits: 1 }) : num(Math.round(a));
  };
  const direction = !trend ? "" : Math.abs(trend.slope) < 1e-9 ? "flat" : trend.slope > 0 ? "up" : "down";
  const yLabel = data ? `${data.label}${data.format === "money" ? " (USD)" : data.format === "pct" ? " (%)" : ""}${running && canRun ? ", running total" : ""}` : "";

  return (
    <div className="overlay overlay-full" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="chart-modal" role="dialog" aria-modal="true" aria-label={`${data?.label ?? "Stat"} chart`} data-testid="stat-chart">
        <header className="chart-modal-head">
          <div>
            <h2>{data?.label ?? "Loading…"}</h2>
            <div className="period-banner" data-testid="chart-period">Showing: <strong>{info.label}</strong> · {data && !info.start ? `${periodLabel({ start: data.start, end: data.start, value: null }, "day")} – today` : info.range}</div>
          </div>
          <button className="icon-btn chart-close" onClick={onClose} aria-label="Close chart">×</button>
        </header>

        <div className="chart-controls">
          <PeriodPicker value={period} onChange={setPeriod} testId="chart-period-select" />
          <label className="row small">Group by
            <select value={bucket} onChange={(e) => setBucket(e.target.value)} aria-label="Group by">
              <option value="auto">Automatic</option><option value="day">Day</option><option value="week">Week</option><option value="month">Month</option>
            </select>
          </label>
          {(metric === "contacts" || metric === "new_contacts") && (
            <div className="segmented">
              <button className={metric === "contacts" ? "active" : ""} onClick={() => setMetric("contacts")}>Total contacts</button>
              <button className={metric === "new_contacts" ? "active" : ""} onClick={() => setMetric("new_contacts")}>New contacts</button>
            </div>
          )}
          {(metric === "views" || metric === "views_gained" || metric === "views_total") && (
            <div className="segmented" data-testid="views-switch">
              <button className={metric === "views_gained" ? "active" : ""} onClick={() => setMetric("views_gained")}>Views gained</button>
              <button className={metric === "views_total" ? "active" : ""} onClick={() => setMetric("views_total")}>Lifetime total</button>
              <button className={metric === "views" ? "active" : ""} onClick={() => setMetric("views")}>On new posts</button>
            </div>
          )}
          {canRun && (
            <div className="segmented">
              <button className={!running ? "active" : ""} onClick={() => setRunning(false)}>Per {unit(data!.bucket)}</button>
              <button className={running ? "active" : ""} onClick={() => setRunning(true)}>Running total</button>
            </div>
          )}
          <label className="row small"><input type="checkbox" checked={showTrend} onChange={(e) => setShowTrend(e.target.checked)} /> Trendline</label>
        </div>

        {data && (
          <div className="chart-summary">
            {data.kind === "sum" && <div><span className="stat-label">Total in period</span><strong>{format(data.total ?? 0)}</strong></div>}
            {data.kind !== "sum" && <div><span className="stat-label">Latest</span><strong>{data.latest === null ? "—" : format(data.latest)}</strong></div>}
            <div><span className="stat-label">Average per {unit(data.bucket)}</span><strong>{avg === null ? "—" : format(avg)}</strong></div>
            <div><span className="stat-label">Best {unit(data.bucket)}</span><strong>{best ? `${format(best.value)}` : "—"}</strong>{best && <span className="small muted">{periodLabel(best, data.bucket)}</span>}</div>
            <div data-testid="trend-summary"><span className="stat-label">Trend</span>
              {trend ? (
                <><strong className={direction === "up" ? "text-green" : direction === "down" ? "text-red" : ""}>
                  {direction === "flat" ? "Flat" : `${direction === "up" ? "▲ +" : "▼ −"}${slopeText(trend.slope)} per ${unit(data.bucket)}`}
                </strong>{trendPct !== null && <span className="small muted">{trendPct >= 0 ? "+" : ""}{Math.round(trendPct)}% across the period</span>}</>
              ) : <strong className="muted">Needs 2+ points</strong>}
            </div>
          </div>
        )}

        <div className="chart-area">
          {loading && !data ? <div className="muted">Loading chart…</div> : data && (
            known.length === 0
              ? <div className="chart-empty"><strong>No data in this period yet.</strong><div className="muted small">Try a longer period, like All time.</div></div>
              : <TrendChart points={points} bucket={data.bucket} format={format} yLabel={yLabel} showTrend={showTrend} />
          )}
        </div>

        <footer className="chart-foot small muted">
          <span>{EXPLAIN[metric]} {data?.note}</span>
          {showTrend && <span className="legend"><span className="legend-line" /> {data?.label} <span className="legend-dash" /> Trendline (straight-line fit)</span>}
        </footer>
      </div>
    </div>
  );
}
