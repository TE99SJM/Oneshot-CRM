/** Channel data: every number a channel's API (or the CRM) gives, the picker to choose which are shown,
 *  and the dashboard panels that add them up per channel type. */
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { toastError } from "../store/toastStore";
import { Empty, Modal } from "./ui";

export type ChannelMetric = {
  key: string; label: string; value: number; unit: string; section: string; window: string; window_label: string;
  source: "api" | "crm"; combine: string; change: number | null; updated_at: string | null; provider: string;
};
export type ChannelData = {
  channel: { id: number; name: string; kind: string; platform: string; active: boolean; group: string; group_label: string };
  metrics: ChannelMetric[]; display: string[]; is_default: boolean;
};
export type CombinedMetric = {
  key: string; label: string; unit: string; section: string; combine: string; total: number; change: number | null;
  windows: string[]; channels: number;
  per_channel: { channel_id: number; channel: string; platform: string; value: number; change: number | null; window_label: string }[];
};
export type CombinedGroup = { key: string; label: string; channels: { id: number; name: string; platform: string }[]; metrics: CombinedMetric[] };

/** Format a metric value by its unit. */
export function fmtMetric(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  switch (unit) {
    case "money": return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 });
    case "pct": return `${Number(v.toFixed(2))}%`;
    case "seconds": { const s = Math.round(v); return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
    case "minutes": return v >= 600 ? `${Math.round(v / 60).toLocaleString()} h` : `${Math.round(v).toLocaleString()} min`;
    case "hours": return `${Number(v.toFixed(1)).toLocaleString()} h`;
    case "stars": return `${v.toFixed(1)} ★`;
    default: return Math.abs(v) >= 100000 ? compact(v) : Number(v.toFixed(2)).toLocaleString();
  }
}
const compact = (v: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v);

export function fmtChange(c: number | null | undefined, unit: string) {
  if (c === null || c === undefined || c === 0) return null;
  return `${c > 0 ? "+" : "−"}${fmtMetric(Math.abs(c), unit)}`;
}

/** Tiles for the metrics chosen on a channel card. */
export function MetricTiles({ data, periodShort }: { data: ChannelData; periodShort: string }) {
  const by = new Map(data.metrics.map((m) => [m.key, m]));
  const shown = data.display.map((k) => by.get(k)).filter(Boolean) as ChannelMetric[];
  if (!shown.length) return <div className="muted small">No data chosen. Click “Choose data”.</div>;
  return (
    <div className="mini-stats">
      {shown.map((m) => {
        const ch = fmtChange(m.change, m.unit);
        return (
          <div key={m.key} title={`${m.label} · ${m.window === "period" ? periodShort : m.window_label} · ${m.source === "api" ? "from the platform" : "worked out by the CRM"}`}>
            <span className="mono">{fmtMetric(m.value, m.unit)}</span>
            <small>{m.label}</small>
            {ch ? <small className={m.change! > 0 ? "text-green" : "text-red"}>{ch} in {periodShort}</small>
              : m.window !== "now" && m.window !== "period" ? <small className="muted">{m.window_label}</small> : null}
          </div>
        );
      })}
    </div>
  );
}

/** "Choose data" modal: every metric the channel has, grouped by section, with checkboxes. */
export function MetricPicker({ data, periodLabel, onClose, onSaved }: {
  data: ChannelData; periodLabel: string; onClose: () => void; onSaved: (d: ChannelData) => void;
}) {
  const [picked, setPicked] = useState<string[]>(data.display);
  const [q, setQ] = useState("");
  const [saving, setSaving] = useState(false);
  const sections = useMemo(() => {
    const out: [string, ChannelMetric[]][] = [];
    for (const m of data.metrics) {
      if (q && !`${m.label} ${m.section} ${m.key}`.toLowerCase().includes(q.toLowerCase())) continue;
      const s = out.find(([n]) => n === m.section);
      if (s) s[1].push(m); else out.push([m.section, [m]]);
    }
    return out;
  }, [data.metrics, q]);
  const toggle = (k: string) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));

  async function save(reset = false) {
    setSaving(true);
    try {
      const r = await api.put<{ display: string[]; is_default: boolean }>(`/metrics/channels/${data.channel.id}/display`,
        reset ? { reset: true } : { keys: data.metrics.map((m) => m.key).filter((k) => picked.includes(k)) });
      const keys = r.is_default ? r.display.filter((k) => data.metrics.some((m) => m.key === k)) : r.display;
      onSaved({ ...data, display: keys, is_default: r.is_default });
      onClose();
    } catch (e) { toastError(e); } finally { setSaving(false); }
  }

  return (
    <Modal wide title={`Choose data · ${data.channel.name}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={() => save(true)} disabled={saving}>Reset to defaults</button>
        <span className="grow" />
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={() => save()} disabled={saving} data-testid="metric-save">Show {picked.length} selected</button>
      </>}>
      <p className="muted small">
        Everything this channel can report. Ticked numbers show on the channel card and are added up with your other
        {" "}{data.channel.group_label.toLowerCase()} on the Dashboard. “Platform” numbers come straight from the channel's API at each sync;
        {" "}“CRM” numbers are worked out from synced posts, orders, contacts and emails for {periodLabel.toLowerCase()}.
      </p>
      <div className="row metric-picker-tools">
        <input placeholder="Search data…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-sm" onClick={() => setPicked(data.metrics.map((m) => m.key))}>Select all</button>
        <button className="btn btn-sm" onClick={() => setPicked([])}>None</button>
      </div>
      {data.metrics.length === 0 && <Empty title="No data yet">Connect this channel (Pull live data) and run a sync.</Empty>}
      {sections.map(([name, list]) => (
        <section key={name} className="metric-section">
          <div className="row-between"><h4>{name}</h4>
            <button className="link-btn small" onClick={() => {
              const keys = list.map((m) => m.key); const all = keys.every((k) => picked.includes(k));
              setPicked((p) => (all ? p.filter((k) => !keys.includes(k)) : [...new Set([...p, ...keys])]));
            }}>toggle section</button></div>
          <div className="metric-options">
            {list.map((m) => (
              <label key={m.key} className={`metric-option ${picked.includes(m.key) ? "on" : ""}`}>
                <input type="checkbox" checked={picked.includes(m.key)} onChange={() => toggle(m.key)} />
                <span className="metric-option-text">
                  <span>{m.label}</span>
                  <small className="muted">{m.window === "period" ? periodLabel : m.window_label} · {m.source === "api" ? "Platform" : "CRM"}</small>
                </span>
                <span className="mono">{fmtMetric(m.value, m.unit)}</span>
              </label>
            ))}
          </div>
        </section>
      ))}
    </Modal>
  );
}

/** Dashboard: one panel per channel type, adding up the data chosen on each channel. */
export function CombinedByType({ groups, periodShort }: { groups: CombinedGroup[]; periodShort: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!groups.length) return null;
  return (
    <section className="combined" data-testid="combined-by-type">
      <h2 className="section-title">Combined by type <span className="muted small">· the data you chose on each channel, added up</span></h2>
      {groups.map((g) => (
        <div key={g.key} className="card combined-group" data-testid={`combined-${g.key}`}>
          <div className="row-between">
            <h3>{g.label}</h3>
            <span className="muted small">{g.channels.map((c) => c.name).join(" · ")}</span>
          </div>
          {g.metrics.length === 0 ? <Empty title="Nothing chosen yet">Pick data on the Channels page.</Empty> : (
            <div className="combined-tiles">
              {g.metrics.map((m) => {
                const id = `${g.key}:${m.key}`;
                const ch = fmtChange(m.change, m.unit);
                const win = m.windows.map((w) => (w === "selected period" ? periodShort : w)).join(" / ");
                return (
                  <button key={m.key} className={`combined-tile ${open === id ? "open" : ""}`} onClick={() => setOpen(open === id ? null : id)}>
                    <span className="small muted">{m.label}</span>
                    <strong className="mono">{fmtMetric(m.total, m.unit)}</strong>
                    <span className="small">
                      {ch && <span className={m.change! > 0 ? "text-green" : "text-red"}>{ch} · </span>}
                      <span className="muted">{win}{m.channels > 1 ? ` · ${m.combine === "avg" ? "avg of" : ""} ${m.channels} channels` : ""}</span>
                    </span>
                    {open === id && (
                      <ul className="combined-breakdown">
                        {m.per_channel.map((p) => (
                          <li key={p.channel_id}><span>{p.channel}</span><span className="mono">{fmtMetric(p.value, m.unit)}</span></li>
                        ))}
                      </ul>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

