import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Drawer, Empty, Field, Modal, statusTone } from "../components/ui";
import { dateOnly, dateTime, fromLocalInput, fullName, money } from "../format";
import { channelName, useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { Activity, ActivityKind, Contact, ContactStatus, Deal, EmailPage } from "../types";

const STATUSES: ContactStatus[] = ["lead", "prospect", "customer", "inactive"];
const blank: Partial<Contact> = { first_name: "", last_name: "", email: "", phone: "", company: "", status: "lead", source_channel_id: null, tags: "", notes: "" };

export default function ContactsPage() {
  const { contacts, contactTotal, contactFilters, setContactFilters, loadContacts, channels, loading } = useCrm();
  const [editing, setEditing] = useState<Partial<Contact> | null>(null);
  const [params, setParams] = useSearchParams();
  const [openId, setOpenIdState] = useState<number | null>(() => Number(params.get("open")) || null);
  const [fetched, setFetched] = useState<Contact | null>(null);
  const setOpenId = (id: number | null) => {
    setOpenIdState(id);
    if (!id && params.get("open")) { params.delete("open"); setParams(params, { replace: true }); }
  };
  // Opened from a link (e.g. an email): the contact may not be in the filtered list.
  useEffect(() => {
    if (openId && !contacts.some((c) => c.id === openId) && fetched?.id !== openId)
      api.get<Contact>(`/contacts/${openId}`).then(setFetched).catch(() => setOpenId(null));
  }, [openId, contacts]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(() => loadContacts().catch(toastError), 250); // debounce search typing
    return () => clearTimeout(t);
  }, [contactFilters, loadContacts]);

  const open = contacts.find((c) => c.id === openId) ?? (fetched?.id === openId ? fetched : null);

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Contacts</h1><p className="muted">{contactTotal} people · leads, prospects and customers</p></div>
        <button className="btn btn-primary" onClick={() => setEditing({ ...blank })}>+ New contact</button>
      </header>

      <div className="toolbar">
        <input className="grow" placeholder="Search name, email, company, phone…" value={contactFilters.q}
               onChange={(e) => setContactFilters({ q: e.target.value })} />
        <select value={contactFilters.status} onChange={(e) => setContactFilters({ status: e.target.value as ContactStatus | "" })}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={contactFilters.channel_id} onChange={(e) => setContactFilters({ channel_id: e.target.value ? Number(e.target.value) : "" })}>
          <option value="">All sources</option>
          {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <input placeholder="Tag" value={contactFilters.tag} onChange={(e) => setContactFilters({ tag: e.target.value })} style={{ width: 120 }} />
      </div>

      <div className="card table-wrap">
        {contacts.length === 0 && !loading.contacts ? <Empty title="No contacts match">Try clearing filters or add a new contact.</Empty> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Status</th><th>Email</th><th>Company</th><th>Source</th><th>Tags</th><th>Added</th></tr></thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => setOpenId(c.id)}>
                  <td><strong>{fullName(c)}</strong></td>
                  <td><Badge tone={statusTone[c.status]}>{c.status}</Badge></td>
                  <td>{c.email}</td>
                  <td>{c.company}</td>
                  <td>{channelName(channels, c.source_channel_id)}</td>
                  <td>{c.tags.split(",").filter(Boolean).map((t) => <span key={t} className="tag">{t.trim()}</span>)}</td>
                  <td className="muted">{dateOnly(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && <ContactForm initial={editing} onClose={() => setEditing(null)} onSaved={(c) => { setEditing(null); setOpenId(c.id); }} />}
      {open && <ContactDrawer contact={open} onClose={() => setOpenId(null)} onEdit={() => setEditing(open)} />}
    </div>
  );
}

export function ContactForm({ initial, onClose, onSaved }: { initial: Partial<Contact>; onClose: () => void; onSaved: (c: Contact) => void }) {
  const { channels, saveContact } = useCrm();
  const [form, setForm] = useState<Partial<Contact>>(initial);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Contact, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const { id, created_at, updated_at, ...data } = form as Contact;
      void created_at; void updated_at;
      onSaved(await saveContact(data, id));
      useToasts.getState().push("Contact saved", "success");
    } catch (err) { toastError(err); } finally { setBusy(false); }
  }

  return (
    <Modal title={form.id ? "Edit contact" : "New contact"} onClose={onClose}
           footer={<><button className="btn" type="button" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="contact-form" disabled={busy}>Save</button></>}>
      <form id="contact-form" className="form-grid" onSubmit={submit}>
        <Field label="First name"><input required value={form.first_name ?? ""} onChange={(e) => set("first_name", e.target.value)} /></Field>
        <Field label="Last name"><input value={form.last_name ?? ""} onChange={(e) => set("last_name", e.target.value)} /></Field>
        <Field label="Email"><input type="email" value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} /></Field>
        <Field label="Phone"><input value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} /></Field>
        <Field label="Company"><input value={form.company ?? ""} onChange={(e) => set("company", e.target.value)} /></Field>
        <Field label="Status">
          <select value={form.status} onChange={(e) => set("status", e.target.value)}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        </Field>
        <Field label="Source channel">
          <select value={form.source_channel_id ?? ""} onChange={(e) => set("source_channel_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Tags" hint="Comma separated"><input value={form.tags ?? ""} onChange={(e) => set("tags", e.target.value)} /></Field>
        <div className="span-2"><Field label="Notes"><textarea rows={3} value={form.notes ?? ""} onChange={(e) => set("notes", e.target.value)} /></Field></div>
      </form>
    </Modal>
  );
}

function ContactDrawer({ contact, onClose, onEdit }: { contact: Contact; onClose: () => void; onEdit: () => void }) {
  const { channels, funnels, deleteContact } = useCrm();
  const [activities, setActivities] = useState<Activity[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [kind, setKind] = useState<ActivityKind>("note");
  const [summary, setSummary] = useState("");
  const [due, setDue] = useState("");
  const [emails, setEmails] = useState<EmailPage | null>(null);

  const load = () => Promise.all([
    api.get<EmailPage>(`/emails?contact_id=${contact.id}&limit=8`).then(setEmails),
    api.get<Activity[]>(`/contacts/${contact.id}/activities`).then(setActivities),
    api.get<Deal[]>(`/contacts/${contact.id}/deals`).then(setDeals),
  ]).catch(toastError);
  useEffect(() => { load(); }, [contact.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function addActivity(e: FormEvent) {
    e.preventDefault();
    if (!summary.trim()) return;
    await api.post("/activities", { kind, summary, contact_id: contact.id, due_at: kind === "task" ? fromLocalInput(due) : null }).catch(toastError);
    setSummary(""); setDue("");
    load();
  }
  async function toggle(a: Activity) { await api.patch(`/activities/${a.id}`, { done: !a.done }).catch(toastError); load(); }
  async function remove() {
    if (!confirm(`Delete ${fullName(contact)}? Their activities are deleted too; deals are kept.`)) return;
    await deleteContact(contact.id).catch(toastError);
    onClose();
  }
  const stageName = (d: Deal) => funnels.find((f) => f.id === d.funnel_id)?.stages.find((s) => s.id === d.stage_id)?.name ?? "";

  return (
    <Drawer title={fullName(contact)} onClose={onClose}>
      <div className="row-between">
        <Badge tone={statusTone[contact.status]}>{contact.status}</Badge>
        <div className="row"><button className="btn btn-sm" onClick={onEdit}>Edit</button><button className="btn btn-sm btn-danger" onClick={remove}>Delete</button></div>
      </div>
      <dl className="details">
        <dt>Email</dt><dd>{contact.email ? <a href={`mailto:${contact.email}`}>{contact.email}</a> : "—"}</dd>
        <dt>Phone</dt><dd>{contact.phone || "—"}</dd>
        <dt>Company</dt><dd>{contact.company || "—"}</dd>
        <dt>Source</dt><dd>{channelName(channels, contact.source_channel_id)}</dd>
        <dt>Tags</dt><dd>{contact.tags || "—"}</dd>
        <dt>Notes</dt><dd className="pre">{contact.notes || "—"}</dd>
      </dl>

      <h3>Deals</h3>
      {deals.length === 0 ? <p className="muted small">No deals yet. Create one from the Pipeline page.</p> : (
        <ul className="list">
          {deals.map((d) => <li key={d.id}><div><strong>{d.title}</strong><div className="muted small">{stageName(d)}</div></div><span className="mono">{money(d.value)}</span></li>)}
        </ul>
      )}

      <h3>Emails {emails && emails.total > 0 && <span className="muted small">({emails.total})</span>}</h3>
      {!emails || emails.total === 0 ? <p className="muted small">No emails with this contact yet{contact.email ? "" : " (add their email address so Gmail mail can be matched)"}.</p> : (
        <>
          <ul className="list">
            {emails.items.map((m) => (
              <li key={m.id}>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="ellipsis"><Badge tone={m.direction === "out" ? "blue" : "neutral"}>{m.direction === "out" ? "Sent" : "In"}</Badge> <strong>{m.subject}</strong></div>
                  <div className="muted small ellipsis">{m.snippet}</div>
                </div>
                <span className="muted small nowrap">{dateOnly(m.sent_at)}</span>
              </li>
            ))}
          </ul>
          <Link className="small" to={`/emails?contact=${contact.id}`}>Open all emails with {contact.first_name} →</Link>
        </>
      )}

      <h3>Activity</h3>
      <form className="activity-form" onSubmit={addActivity}>
        <select value={kind} onChange={(e) => setKind(e.target.value as ActivityKind)}>
          {["note", "call", "email", "dm", "meeting", "task"].map((k) => <option key={k}>{k}</option>)}
        </select>
        <input className="grow" placeholder={kind === "task" ? "Follow-up to do…" : "What happened?"} value={summary} onChange={(e) => setSummary(e.target.value)} />
        {kind === "task" && <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />}
        <button className="btn btn-primary btn-sm">Add</button>
      </form>
      <ul className="timeline">
        {activities.map((a) => (
          <li key={a.id} className={a.done ? "done" : ""}>
            <Badge>{a.kind}</Badge>
            <div className="grow"><div>{a.summary}</div><div className="muted small">{dateTime(a.created_at)}{a.due_at && ` · due ${dateTime(a.due_at)}`}</div></div>
            {a.kind === "task" && <input type="checkbox" checked={a.done} onChange={() => toggle(a)} aria-label="Done" />}
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
