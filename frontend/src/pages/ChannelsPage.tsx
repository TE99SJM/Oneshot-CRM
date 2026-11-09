import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty, Field, Modal } from "../components/ui";
import { ChannelData, MetricPicker, MetricTiles } from "../components/ChannelData";
import { Period, PeriodPicker, loadPeriod, periodInfo, savePeriod, tzOffset } from "../components/Period";
import { money, num } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { Channel, ChannelKind, Integration } from "../types";

function ago(iso: string | null) {
  if (!iso) return "not synced yet";
  const min = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
  if (min < 1) return "synced just now";
  if (min < 60) return `synced ${min} min ago`;
  if (min < 48 * 60) return `synced ${Math.round(min / 60)} h ago`;
  return `synced ${Math.round(min / 1440)} days ago`;
}

// channel platform -> integration that can pull its data
const LIVE_PROVIDERS: Record<string, string> = {
  youtube: "youtube", facebook: "facebook", instagram: "instagram", square: "square", ebay: "ebay", gmail: "gmail", rumble: "rumble", twitch: "twitch", tiktok: "tiktok",
};

function safeUrl(u: string) {
  const v = u.trim();
  if (!v) return "";
  return /^https?:\/\//i.test(v) ? v : `https://${v}`;
}

const KINDS: ChannelKind[] = ["social", "marketplace", "website", "email", "direct", "ads", "other"];
const KIND_LABEL: Record<ChannelKind, string> = {
  social: "Social", marketplace: "Marketplace", website: "Website / store", email: "Email list", direct: "Direct / referral", ads: "Paid ads", other: "Other",
};
const blank: Partial<Channel> = { name: "", kind: "social", platform: "", handle: "", url: "", followers: 0, monthly_cost: 0, active: true, notes: "" };

export default function ChannelsPage() {
  const { channels, loadChannels } = useCrm();
  const toast = useToasts((s) => s.push);
  const navigate = useNavigate();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  useEffect(() => { api.get<Integration[]>("/integrations").then(setIntegrations).catch(() => {}); }, [channels]);

  async function importCsv(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData(); form.append("file", file);
    try {
      const r = await api.upload<{ created: number; updated: number; skipped: number; errors: string[] }>("/channels/import", form);
      toast(`Channels: ${r.created} added, ${r.updated} updated${r.skipped ? `, ${r.skipped} skipped` : ""}`, "success");
      r.errors.slice(0, 5).forEach((m) => toast(m, "error"));
      await loadChannels();
    } catch (err) { toastError(err); } finally { e.target.value = ""; }
  }
  const [period, setPeriodState] = useState<Period>(loadPeriod);
  const info = periodInfo(period);
  const setPeriod = (p: Period) => { savePeriod(p); setPeriodState(p); };
  const [data, setData] = useState<Record<number, ChannelData>>({});
  const [picking, setPicking] = useState<ChannelData | null>(null);
  useEffect(() => {
    api.get<ChannelData[]>("/metrics/channels", { start: info.start, end: info.end, tz_offset: tzOffset() })
      .then((rows) => setData(Object.fromEntries(rows.map((r) => [r.channel.id, r])))).catch(() => {});
  }, [channels, info.start, info.end]);
  const [editing, setEditing] = useState<Partial<Channel> | null>(null);
  const [kind, setKind] = useState<ChannelKind | "">("");
  const shown = channels.filter((c) => !kind || c.kind === kind);

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Channels</h1><p className="muted">Social accounts and sales channels. Use “Choose data” on a card to pick which numbers it shows.</p></div>
        <div className="row">
          <button className="btn" title="Download all channels in the import format (an empty CRM gives a blank template)"
            onClick={() => api.download("/channels/export", "channels.csv").catch(toastError)}>Export / template</button>
          <label className="btn" title="CSV columns: Name, Type, Platform, Handle, URL, Followers / subscribers, Monthly cost (USD), Active, Notes. Matching names are updated.">
            Import CSV<input type="file" accept=".csv,.tsv,.txt,text/csv" hidden onChange={importCsv} /></label>
          <button className="btn btn-primary" onClick={() => setEditing({ ...blank })}>+ New channel</button>
        </div>
      </header>
      <div className="toolbar">
        <PeriodPicker value={period} onChange={setPeriod} testId="channels-period" />
        <div className="segmented">
          <button className={kind === "" ? "active" : ""} onClick={() => setKind("")}>All</button>
          {KINDS.map((k) => <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>{KIND_LABEL[k]}</button>)}
        </div>
      </div>
      {shown.length === 0 ? <div className="card"><Empty title="No channels yet">Add YouTube, Facebook, your store, email list, etc.</Empty></div> : (
        <div className="channel-grid">
          {shown.map((c) => {
            const roi = c.monthly_cost ? (c.won_revenue ?? 0) / c.monthly_cost : null;
            return (
              <article key={c.id} className={`card channel-card ${c.active ? "" : "inactive"}`} onClick={() => setEditing(c)}>
                <div className="row-between">
                  <div><strong>{c.name}</strong><div className="muted small">{c.platform || KIND_LABEL[c.kind]}{c.handle && ` · ${c.handle}`}</div></div>
                  <Badge tone={c.active ? "blue" : "neutral"}>{KIND_LABEL[c.kind]}</Badge>
                </div>
                <div className="row channel-links">
                  {c.url ? (
                    <a className="btn btn-sm" href={safeUrl(c.url)} target="_blank" rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}>Open channel ↗</a>
                  ) : <span className="muted small">No URL yet</span>}
                  {(() => {
                    const live = integrations.filter((i) => i.channel_id === c.id && i.enabled);
                    if (!live.length) {
                      const provider = (c.platform || "").toLowerCase() === "tiktok" && c.kind === "marketplace" ? "tiktok_shop" : LIVE_PROVIDERS[(c.platform || "").toLowerCase()];
                      return provider ? (
                        <button className="btn btn-sm btn-primary" onClick={(e) => { e.stopPropagation(); navigate(`/integrations?provider=${provider}&channel=${c.id}`); }}>
                          Pull live data</button>
                      ) : <Badge tone="neutral">Manual stats</Badge>;
                    }
                    const i = live[0];
                    return <span title={i.last_error || undefined}><Badge tone={i.last_status === "error" ? "red" : "green"}>
                      {i.last_status === "error" ? "Live sync error" : `Live · ${ago(i.last_sync_at)}`}</Badge></span>;
                  })()}
                </div>
{data[c.id] ? <MetricTiles data={data[c.id]} periodShort={info.short} /> : (
                <div className="mini-stats">
                  <div><span className="mono">{num(c.followers)}</span><small>audience</small></div>
                  <div><span className="mono">{num(c.contacts)}</span><small>leads</small></div>
                  <div><span className="mono">{num(c.open_deals)}</span><small>open deals</small></div>
                  <div><span className="mono">{money(c.won_revenue)}</span><small>won</small></div>
                  <div><span className="mono">{num(c.posts)}</span><small>posts</small></div>
                  <div><span className="mono">{num(c.views)}</span><small>lifetime views</small></div>
                </div>)}
                <div className="row-between">
                  <span className="muted small">{data[c.id] ? `${data[c.id].metrics.length} data points available` : ""}</span>
                  {data[c.id] && <button className="btn btn-sm" data-testid={`choose-data-${c.id}`}
                    onClick={(e) => { e.stopPropagation(); setPicking(data[c.id]); }}>Choose data</button>}
                </div>
                {c.monthly_cost > 0 && <div className="muted small">{money(c.monthly_cost)}/mo{roi !== null && ` · ${roi.toFixed(1)}× lifetime return on monthly cost`}</div>}
              </article>
            );
          })}
        </div>
      )}
      {picking && <MetricPicker data={picking} periodLabel={info.label} onClose={() => setPicking(null)}
        onSaved={(d) => setData((x) => ({ ...x, [d.channel.id]: d }))} />}
      {editing && <ChannelForm initial={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ChannelForm({ initial, onClose }: { initial: Partial<Channel>; onClose: () => void }) {
  const { saveChannel, deleteChannel } = useCrm();
  const [form, setForm] = useState<Partial<Channel>>(initial);
  const set = (k: keyof Channel, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const { name, kind, platform, handle, url, followers, monthly_cost, active, notes } = form;
    try {
      await saveChannel({ name, kind, platform, handle, url, followers: Number(followers) || 0, monthly_cost: Number(monthly_cost) || 0, active, notes }, form.id);
      onClose();
    } catch (err) { toastError(err); }
  }
  async function remove() {
    if (form.id && confirm("Delete this channel? Contacts, deals and posts keep their data but lose the channel link.")) {
      await deleteChannel(form.id).catch(toastError); onClose();
    }
  }

  return (
    <Modal title={form.id ? "Edit channel" : "New channel"} onClose={onClose}
           footer={<>{form.id && <button type="button" className="btn btn-danger" onClick={remove}>Delete</button>}<span className="grow" />
             <button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="channel-form">Save</button></>}>
      <form id="channel-form" className="form-grid" onSubmit={submit}>
        <Field label="Name"><input required autoFocus value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Type"><select value={form.kind} onChange={(e) => set("kind", e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></Field>
        <Field label="Platform" hint="youtube, facebook, rumble, etsy…"><input value={form.platform ?? ""} onChange={(e) => set("platform", e.target.value)} /></Field>
        <Field label="Handle"><input value={form.handle ?? ""} onChange={(e) => set("handle", e.target.value)} /></Field>
        <div className="span-2"><Field label="URL"><input value={form.url ?? ""} onChange={(e) => set("url", e.target.value)} placeholder="https://" /></Field></div>
        <Field label="Followers / subscribers"><input type="number" min={0} value={form.followers ?? 0} onChange={(e) => set("followers", e.target.value)} /></Field>
        <Field label="Monthly cost (USD)"><input type="number" min={0} step="0.01" value={form.monthly_cost ?? 0} onChange={(e) => set("monthly_cost", e.target.value)} /></Field>
        <label className="check span-2"><input type="checkbox" checked={!!form.active} onChange={(e) => set("active", e.target.checked)} /> Active</label>
        <div className="span-2"><Field label="Notes"><textarea rows={3} value={form.notes ?? ""} onChange={(e) => set("notes", e.target.value)} /></Field></div>
      </form>
    </Modal>
  );
}
