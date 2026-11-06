import { DragEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { Empty, Field, Modal } from "../components/ui";
import { dateOnly, fullName, money } from "../format";
import { channelName, useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { Contact, Deal, Funnel, Stage, StageKind } from "../types";
import { api } from "../api/client";
import { DateRangePicker, Range, defaultRange, inRange } from "../components/DateRange";

export default function PipelinePage() {
  const { funnels, deals, loadDeals, moveDeal, channels, loadFunnels } = useCrm();
  // Syncs (Square, eBay) can create funnels, so refresh the list whenever the Pipeline opens.
  useEffect(() => { loadFunnels().catch(toastError); }, [loadFunnels]);
  const [funnelId, setFunnelId] = useState<number | null>(null);
  const [editingDeal, setEditingDeal] = useState<Partial<Deal> | null>(null);
  const [editingFunnel, setEditingFunnel] = useState<Partial<Funnel> | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [range, setRange] = useState<Range>(() => defaultRange());
  // A deal counts in the range if it was created or closed (won/lost) inside it.
  const shown = (d: Deal) => (!range.from && !range.to) || inRange(d.created_at, range) || inRange(d.closed_at, range);

  const funnel = funnels.find((f) => f.id === funnelId) ?? funnels[0];
  useEffect(() => { if (funnel) loadDeals(funnel.id).catch(toastError); }, [funnel?.id, loadDeals]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.get<{ items: Contact[] }>("/contacts", { limit: 500 }).then((r) => setContacts(r.items)).catch(toastError); }, []);

  const byStage = useMemo(() => {
    const m = new Map<number, Deal[]>();
    deals.filter((d) => d.funnel_id === funnel?.id && shown(d)).forEach((d) => m.set(d.stage_id, [...(m.get(d.stage_id) ?? []), d]));
    return m;
  }, [deals, funnel?.id, range]); // eslint-disable-line react-hooks/exhaustive-deps

  function onDrop(e: DragEvent, stage: Stage) {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/deal"));
    const deal = deals.find((d) => d.id === id);
    if (deal && deal.stage_id !== stage.id) {
      moveDeal(id, stage.id).then(() => {
        if (stage.kind === "won") useToasts.getState().push(`Won: ${deal.title} (${money(deal.value)})`, "success");
      }).catch(toastError);
    }
  }

  const contactName = (id: number | null) => { const c = contacts.find((x) => x.id === id); return c ? fullName(c) : ""; };

  if (!funnels.length) {
    return (
      <div className="page">
        <header className="page-head"><h1>Pipeline</h1></header>
        <div className="card"><Empty title="No sales funnels yet">
          <p>A funnel is an ordered list of stages a deal moves through (e.g. Awareness → Interest → Won).</p>
          <button className="btn btn-primary" onClick={() => setEditingFunnel({ name: "", description: "" })}>Create your first funnel</button>
        </Empty></div>
        {editingFunnel && <FunnelForm initial={editingFunnel} onClose={() => setEditingFunnel(null)} onSaved={(f) => { setFunnelId(f.id); setEditingFunnel(null); }} />}
      </div>
    );
  }

  const open = funnel ? deals.filter((d) => d.funnel_id === funnel.id && d.status === "open" && shown(d)) : [];

  return (
    <div className="page page-full">
      <header className="page-head">
        <div>
          <h1>Pipeline</h1>
          <p className="muted">{open.length} open deals · {money(open.reduce((s, d) => s + d.value, 0))} in play. Drag cards between stages. Showing deals created or closed in the selected range.</p>
        </div>
        <div className="row">
          <select value={funnel?.id} onChange={(e) => setFunnelId(Number(e.target.value))}>
            {funnels.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
          <button className="btn" onClick={() => setEditingFunnel(funnel)}>Edit funnel</button>
          <button className="btn" onClick={() => setEditingFunnel({ name: "", description: "" })}>+ Funnel</button>
          <button className="btn btn-primary" onClick={() => setEditingDeal({ title: "", value: 0, funnel_id: funnel.id, stage_id: funnel.stages[0]?.id })}>+ Deal</button>
        </div>
      </header>

      <div className="toolbar">
        <DateRangePicker value={range} onChange={setRange} testId="pipeline-range" />
      </div>

      <div className="board">
        {funnel.stages.map((s) => {
          const list = byStage.get(s.id) ?? [];
          return (
            <section key={s.id} className={`board-col col-${s.kind} ${dragOver === s.id ? "drag-over" : ""}`}
                     onDragOver={(e) => { e.preventDefault(); setDragOver(s.id); }} onDragLeave={() => setDragOver(null)} onDrop={(e) => onDrop(e, s)}>
              <header>
                <div className="row-between"><strong>{s.name}</strong><span className="muted small">{s.probability}%</span></div>
                <div className="muted small">{list.length} · {money(list.reduce((a, d) => a + d.value, 0))}</div>
              </header>
              <div className="board-cards">
                {list.map((d) => (
                  <article key={d.id} className="deal-card" draggable onDragStart={(e) => e.dataTransfer.setData("text/deal", String(d.id))}
                           onClick={() => setEditingDeal(d)}>
                    <div className="row-between"><strong>{d.title}</strong><span className="mono">{money(d.value)}</span></div>
                    {d.contact_id && <div className="small">{contactName(d.contact_id)}</div>}
                    <div className="muted small">{channelName(channels, d.channel_id)}{d.expected_close && ` · ${dateOnly(d.expected_close)}`}</div>
                  </article>
                ))}
                <button className="btn btn-ghost btn-sm add-card" onClick={() => setEditingDeal({ title: "", value: 0, funnel_id: funnel.id, stage_id: s.id })}>+ Add</button>
              </div>
            </section>
          );
        })}
      </div>

      {editingDeal && <DealForm initial={editingDeal} funnel={funnel} contacts={contacts} onClose={() => setEditingDeal(null)} />}
      {editingFunnel && <FunnelForm initial={editingFunnel} onClose={() => setEditingFunnel(null)} onSaved={(f) => { setFunnelId(f.id); setEditingFunnel(null); }} />}
    </div>
  );
}

function DealForm({ initial, funnel, contacts, onClose }: { initial: Partial<Deal>; funnel: Funnel; contacts: Contact[]; onClose: () => void }) {
  const { channels, saveDeal, deleteDeal } = useCrm();
  const [form, setForm] = useState<Partial<Deal>>(initial);
  const set = (k: keyof Deal, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const payload = { title: form.title, value: Number(form.value) || 0, stage_id: form.stage_id, contact_id: form.contact_id ?? null,
                        channel_id: form.channel_id ?? null, expected_close: form.expected_close || null, notes: form.notes ?? "" };
      await saveDeal(form.id ? payload : { ...payload, funnel_id: funnel.id }, form.id);
      onClose();
    } catch (err) { toastError(err); }
  }
  async function remove() {
    if (form.id && confirm("Delete this deal?")) { await deleteDeal(form.id).catch(toastError); onClose(); }
  }

  return (
    <Modal title={form.id ? "Edit deal" : "New deal"} onClose={onClose}
           footer={<>{form.id && <button className="btn btn-danger" type="button" onClick={remove}>Delete</button>}<span className="grow" />
             <button className="btn" type="button" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="deal-form">Save</button></>}>
      <form id="deal-form" className="form-grid" onSubmit={submit}>
        <div className="span-2"><Field label="Title"><input required autoFocus value={form.title ?? ""} onChange={(e) => set("title", e.target.value)} /></Field></div>
        <Field label="Value (USD)"><input type="number" min={0} step="0.01" value={form.value ?? 0} onChange={(e) => set("value", e.target.value)} /></Field>
        <Field label="Stage">
          <select value={form.stage_id} onChange={(e) => set("stage_id", Number(e.target.value))}>
            {funnel.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
        <Field label="Contact">
          <select value={form.contact_id ?? ""} onChange={(e) => set("contact_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>{contacts.map((c) => <option key={c.id} value={c.id}>{fullName(c)}{c.company && ` (${c.company})`}</option>)}
          </select>
        </Field>
        <Field label="Sales channel">
          <select value={form.channel_id ?? ""} onChange={(e) => set("channel_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Expected close"><input type="date" value={form.expected_close ?? ""} onChange={(e) => set("expected_close", e.target.value)} /></Field>
        <div className="span-2"><Field label="Notes"><textarea rows={3} value={form.notes ?? ""} onChange={(e) => set("notes", e.target.value)} /></Field></div>
      </form>
    </Modal>
  );
}

type StageDraft = { id?: number; name: string; probability: number; kind: StageKind };
const DEFAULT_DRAFT: StageDraft[] = [
  { name: "Awareness", probability: 5, kind: "open" }, { name: "Interest", probability: 15, kind: "open" },
  { name: "Consideration", probability: 35, kind: "open" }, { name: "Intent", probability: 60, kind: "open" },
  { name: "Won", probability: 100, kind: "won" }, { name: "Lost", probability: 0, kind: "lost" },
];

function FunnelForm({ initial, onClose, onSaved }: { initial: Partial<Funnel>; onClose: () => void; onSaved: (f: Funnel) => void }) {
  const { saveFunnel, deleteFunnel } = useCrm();
  const [name, setName] = useState(initial.name ?? "");
  const [description, setDescription] = useState(initial.description ?? "");
  const [stages, setStages] = useState<StageDraft[]>(
    initial.stages?.map(({ id, name, probability, kind }) => ({ id, name, probability, kind })) ?? DEFAULT_DRAFT);

  const update = (i: number, patch: Partial<StageDraft>) => setStages((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const move = (i: number, dir: -1 | 1) => setStages((s) => {
    const j = i + dir; if (j < 0 || j >= s.length) return s;
    const copy = [...s]; [copy[i], copy[j]] = [copy[j], copy[i]]; return copy;
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    try { onSaved(await saveFunnel({ name, description, stages }, initial.id)); } catch (err) { toastError(err); }
  }
  async function remove() {
    if (initial.id && confirm(`Delete funnel "${initial.name}" and all of its deals?`)) {
      await deleteFunnel(initial.id).catch(toastError); onClose();
    }
  }

  return (
    <Modal wide title={initial.id ? "Edit funnel" : "New funnel"} onClose={onClose}
           footer={<>{initial.id && <button type="button" className="btn btn-danger" onClick={remove}>Delete funnel</button>}<span className="grow" />
             <button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="funnel-form">Save</button></>}>
      <form id="funnel-form" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Name"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <h3>Stages</h3>
        <p className="muted small">Probability drives the weighted pipeline. "Won" and "Lost" stages close deals automatically.</p>
        <div className="stage-editor">
          {stages.map((s, i) => (
            <div key={s.id ?? `new-${i}`} className="stage-row">
              <span className="muted mono">{i + 1}</span>
              <input required value={s.name} onChange={(e) => update(i, { name: e.target.value })} />
              <input type="number" min={0} max={100} value={s.probability} onChange={(e) => update(i, { probability: Number(e.target.value) })} aria-label="Probability" />
              <select value={s.kind} onChange={(e) => update(i, { kind: e.target.value as StageKind })}>
                <option value="open">open</option><option value="won">won</option><option value="lost">lost</option>
              </select>
              <button type="button" className="icon-btn" onClick={() => move(i, -1)} aria-label="Move up">↑</button>
              <button type="button" className="icon-btn" onClick={() => move(i, 1)} aria-label="Move down">↓</button>
              <button type="button" className="icon-btn" onClick={() => setStages((x) => x.filter((_, j) => j !== i))} aria-label="Remove">×</button>
            </div>
          ))}
        </div>
        <button type="button" className="btn btn-sm" onClick={() => setStages((s) => [...s, { name: "New stage", probability: 50, kind: "open" }])}>+ Add stage</button>
      </form>
    </Modal>
  );
}
