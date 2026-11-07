import { useEffect, useMemo, useRef, useState } from "react";

export type SeriesPoint = { start: string; end: string; value: number | null };

/** Least-squares line through the points that have a value. Returns null with fewer than 2 points. */
export function linearTrend(values: (number | null)[]) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (pts.length < 2) return null;
  const n = pts.length;
  const mx = pts.reduce((s, p) => s + p[0], 0) / n;
  const my = pts.reduce((s, p) => s + p[1], 0) / n;
  const sxx = pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  const slope = sxx ? pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / sxx : 0;
  const intercept = my - slope * mx;
  return { slope, intercept, at: (i: number) => intercept + slope * i };
}

const shortDate = (s: string, withYear = false) =>
  new Date(`${s}T12:00:00`).toLocaleDateString(undefined, withYear ? { month: "short", day: "numeric", year: "numeric" } : { month: "short", day: "numeric" });
export function periodLabel(p: SeriesPoint, bucket: string) {
  if (bucket === "month") return new Date(`${p.start}T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
  if (bucket === "week") return `${shortDate(p.start)} – ${shortDate(p.end, true)}`;
  return shortDate(p.start, true);
}
const axisLabel = (p: SeriesPoint, bucket: string) =>
  bucket === "month" ? new Date(`${p.start}T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" }) : shortDate(p.start);

function niceTicks(min: number, max: number, count = 5) {
  if (max === min) { max = min + 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

export function TrendChart({ points, bucket, format, yLabel, showTrend = true, compact = false }: {
  points: SeriesPoint[]; bucket: string; format: (n: number) => string; yLabel: string; showTrend?: boolean; compact?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: compact ? 230 : 420 });
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.max(240, Math.round(e.contentRect.width)), h = Math.max(compact ? 180 : 260, Math.round(e.contentRect.height));
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [compact]);
  const W = size.w, H = size.h;
  const M = compact ? { l: 62, r: 12, t: 12, b: 30 } : { l: 84, r: 24, t: 20, b: 64 };
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const values = points.map((p) => p.value);
  const trend = useMemo(() => (showTrend ? linearTrend(values) : null), [points, showTrend]); // eslint-disable-line react-hooks/exhaustive-deps

  const known = values.filter((v): v is number => v !== null);
  const firstI = values.findIndex((v) => v !== null);
  const lastI = values.length - 1 - [...values].reverse().findIndex((v) => v !== null);
  const trendVals = trend ? [trend.at(firstI), trend.at(lastI)] : [];
  const ticks = niceTicks(Math.min(0, ...known, ...trendVals), Math.max(1, ...known, ...trendVals));
  const yMin = ticks[0], yMax = ticks[ticks.length - 1];
  const n = points.length;
  const x = (i: number) => M.l + (n <= 1 ? (W - M.l - M.r) / 2 : (i / (n - 1)) * (W - M.l - M.r));
  const y = (v: number) => M.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - M.t - M.b);

  // line segments break where a period has no value (e.g. no closed deals that week)
  const segments: string[] = [];
  let cur = "";
  points.forEach((p, i) => {
    if (p.value === null) { if (cur) segments.push(cur); cur = ""; return; }
    cur += `${cur ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
  });
  if (cur) segments.push(cur);
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - M.l - M.r) / (bucket === "week" ? 70 : 64)))));
  const dots = n <= 62;

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const svg = ref.current; if (!svg || n === 0) return;
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = n <= 1 ? 0 : Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  }

  const h = hover !== null ? points[hover] : null;
  return (
    <div className={`trend-chart ${compact ? "compact" : ""}`} ref={wrap}>
      <svg ref={ref} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${yLabel} over time`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} data-testid="trend-chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={M.l - 10} y={y(t) + 4} textAnchor="end" className="axis-text">{format(t)}</text>
          </g>
        ))}
        {points.map((p, i) => (i % labelEvery === 0 || i === n - 1) && (n - 1 - i >= labelEvery / 2 || i === n - 1) ? (
          <text key={p.start} x={x(i)} y={H - M.b + 22} textAnchor="middle" className="axis-text">{axisLabel(p, bucket)}</text>
        ) : null)}
        {!compact && <>
          <text x={(M.l + W - M.r) / 2} y={H - 10} textAnchor="middle" className="axis-title">
            Time ({bucket === "day" ? "by day" : bucket === "week" ? "by week, Monday start" : "by month"})
          </text>
          <text transform={`translate(16 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle" className="axis-title">{yLabel}</text>
        </>}
        {segments.map((d, i) => <path key={i} d={d} className="series-line" />)}
        {dots && points.map((p, i) => p.value !== null && <circle key={p.start} cx={x(i)} cy={y(p.value)} r={hover === i ? 6 : 3.5} className="series-dot" />)}
        {trend && lastI > firstI && (
          <line x1={x(firstI)} y1={y(trend.at(firstI))} x2={x(lastI)} y2={y(trend.at(lastI))} className="trend-line" data-testid="trend-line" />
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} className="hover-line" />}
      </svg>
      {h && hover !== null && (
        <div className="chart-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <div className="small muted">{periodLabel(h, bucket)}</div>
          <strong>{h.value === null ? "No data" : format(h.value)}</strong>
          {trend && hover >= firstI && hover <= lastI && <div className="small muted">Trend: {format(trend.at(hover))}</div>}
        </div>
      )}
    </div>
  );
}
