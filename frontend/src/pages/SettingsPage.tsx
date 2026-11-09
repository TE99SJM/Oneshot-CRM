import { ChangeEvent, FormEvent, useState } from "react";
import { api } from "../api/client";
import { Field } from "../components/ui";
import OrderAlerts from "../components/OrderAlerts";
import { useAuth } from "../store/authStore";
import { useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";

export default function SettingsPage() {
  const user = useAuth((s) => s.user);
  const { loadReference, loadContacts } = useCrm();
  const toast = useToasts((s) => s.push);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    try { await api.post("/auth/password", { current_password: current, new_password: next }); toast("Password updated", "success"); setCurrent(""); setNext(""); }
    catch (err) { toastError(err); }
  }
  async function seed() {
    try { const r = await api.post<Record<string, number>>("/demo/seed"); await loadReference(); toast(`Demo data loaded: ${r.contacts} contacts, ${r.deals} deals, ${r.posts} posts`, "success"); }
    catch (err) { toastError(err); }
  }
  async function importCsv(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData(); form.append("file", file);
    try { const r = await api.upload<{ created: number; skipped: number }>("/contacts/import", form); toast(`Imported ${r.created}, skipped ${r.skipped}`, "success"); loadContacts(); }
    catch (err) { toastError(err); } finally { e.target.value = ""; }
  }

  return (
    <div className="page">
      <header className="page-head"><div><h1>Settings</h1><p className="muted">Signed in as {user?.email}</p></div></header>
      <OrderAlerts />
      <section className="grid-2">
        <form className="card" onSubmit={changePassword}>
          <h3>Change password</h3>
          <Field label="Current password"><input type="password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
          <Field label="New password" hint="At least 8 characters"><input type="password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <button className="btn btn-primary">Update password</button>
        </form>
        <div className="card">
          <h3>Contacts import / export</h3>
          <p className="muted small">CSV columns: first_name, last_name, email, phone, company, status, tags, notes, source_channel (channel name). Existing emails are skipped.</p>
          <div className="row">
            <button className="btn" onClick={() => api.download("/contacts/export.csv", "contacts.csv").catch(toastError)}>Export CSV</button>
            <label className="btn">Import CSV<input type="file" accept=".csv,text/csv" hidden onChange={importCsv} /></label>
          </div>
          <h3>Sample data</h3>
          <p className="muted small">Fills an empty CRM with demo channels, contacts, two funnels, deals, posts and tasks so you can test every screen.</p>
          <button className="btn" onClick={seed}>Load demo data</button>
          <h3>API</h3>
          <p className="muted small">Interactive API docs (Swagger) are served by the backend at <a href="/docs" target="_blank" rel="noreferrer">/docs</a>.</p>
        </div>
      </section>
    </div>
  );
}
