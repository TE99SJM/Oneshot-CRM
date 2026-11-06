import { FormEvent, useState } from "react";
import { Badge, Empty, Field, Modal } from "../components/ui";
import { money, num } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { Channel, ChannelKind } from "../types";

const KINDS: ChannelKind[] = ["social", "marketplace", "website", "email", "direct", "ads", "other"];
const KIND_LABEL: Record<ChannelKind, string> = {
  social: "Social", marketplace: "Marketplace", website: "Website / store", email: "Email list", direct: "Direct / referral", ads: "Paid ads", other: "Other",
};
const blank: Partial<Channel> = { name: "", kind: "social", platform: "", handle: "", url: "", followers: 0, monthly_cost: 0, active: true, notes: "" };

export default function ChannelsPage() {
  const { channels } = useCrm();
  const [editing, setEditing] = useState<Partial<Channel> | null>(null);
  const [kind, setKind] = useState<ChannelKind | "">("");
  const shown = channels.filter((c) => !kind || c.kind === kind);

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Channels</h1><p className="muted">Social accounts and sales channels, with attributed leads, deals and revenue.</p></div>
        <button className="btn btn-primary" onClick={() => setEditing({ ...blank })}>+ New channel</button>
      </header>
      <div className="toolbar">
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
                <div className="mini-stats">
                  <div><span className="mono">{num(c.followers)}</span><small>audience</small></div>
                  <div><span className="mono">{num(c.contacts)}</span><small>leads</small></div>
                  <div><span className="mono">{num(c.open_deals)}</span><small>open deals</small></div>
                  <div><span className="mono">{money(c.won_revenue)}</span><small>won</small></div>
                  <div><span className="mono">{num(c.posts)}</span><small>posts</small></div>
                  <div><span className="mono">{num(c.views)}</span><small>views</small></div>
                </div>
                {c.monthly_cost > 0 && <div className="muted small">{money(c.monthly_cost)}/mo{roi !== null && ` · ${roi.toFixed(1)}× lifetime return on monthly cost`}</div>}
              </article>
            );
          })}
        </div>
      )}
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
