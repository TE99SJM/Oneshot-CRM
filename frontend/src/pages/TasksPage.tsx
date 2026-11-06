import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { Empty } from "../components/ui";
import { dateTime, fromLocalInput, fullName, parseUtc } from "../format";
import { toastError } from "../store/toastStore";
import type { Activity, Contact } from "../types";

export default function TasksPage() {
  const [tasks, setTasks] = useState<Activity[]>([]);
  const [showDone, setShowDone] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [summary, setSummary] = useState("");
  const [due, setDue] = useState("");
  const [contactId, setContactId] = useState<number | "">("");

  const load = () => (showDone
    ? api.get<Activity[]>("/activities", { kind: "task", limit: 300 })
    : api.get<Activity[]>("/activities", { open_tasks: true, limit: 300 })).then(setTasks).catch(toastError);
  useEffect(() => { load(); }, [showDone]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.get<{ items: Contact[] }>("/contacts", { limit: 500 }).then((r) => setContacts(r.items)).catch(toastError); }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    await api.post("/activities", { kind: "task", summary, due_at: fromLocalInput(due), contact_id: contactId || null }).catch(toastError);
    setSummary(""); setDue(""); setContactId("");
    load();
  }
  async function toggle(t: Activity) { await api.patch(`/activities/${t.id}`, { done: !t.done }).catch(toastError); load(); }
  async function remove(t: Activity) { await api.del(`/activities/${t.id}`).catch(toastError); load(); }
  const who = (id: number | null) => { const c = contacts.find((x) => x.id === id); return c ? fullName(c) : ""; };
  const now = new Date();

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Tasks</h1><p className="muted">Follow-ups for leads, customers and sponsors.</p></div>
        <label className="check"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show completed</label>
      </header>
      <form className="card toolbar" onSubmit={add}>
        <input className="grow" required placeholder="New follow-up…" value={summary} onChange={(e) => setSummary(e.target.value)} />
        <select value={contactId} onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">No contact</option>{contacts.map((c) => <option key={c.id} value={c.id}>{fullName(c)}</option>)}
        </select>
        <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
        <button className="btn btn-primary">Add task</button>
      </form>
      <div className="card">
        {tasks.length === 0 ? <Empty title="No tasks" /> : (
          <ul className="list">
            {tasks.map((t) => {
              const overdue = !t.done && t.due_at && parseUtc(t.due_at) < now;
              return (
                <li key={t.id} className={t.done ? "done" : ""}>
                  <label className="check grow"><input type="checkbox" checked={t.done} onChange={() => toggle(t)} />
                    <div><div>{t.summary}</div><div className={`small ${overdue ? "text-red" : "muted"}`}>{who(t.contact_id)}{t.due_at && ` · due ${dateTime(t.due_at)}`}{overdue && " · overdue"}</div></div>
                  </label>
                  <button className="icon-btn" onClick={() => remove(t)} aria-label="Delete">×</button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
