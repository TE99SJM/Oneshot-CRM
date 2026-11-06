import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty, Field, Modal } from "../components/ui";
import { dateTime, money, num } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { Channel, Integration, Provider } from "../types";

/** Pre-fill connect-form values from an existing channel record. */
function prefill(provider: string, ch?: Channel): Record<string, string> {
  if (!ch) return {};
  const handle = (ch.handle || "").trim();
  const url = (ch.url || "").trim();
  switch (provider) {
    case "youtube": return { channel: handle || (url.match(/youtube\.com\/(@[^/?]+|channel\/(UC[\w-]+))/)?.[2] ?? url.match(/youtube\.com\/(@[^/?]+)/)?.[1] ?? "") };
    case "rumble": return url.includes("rumble.com/c/") || url.includes("rumble.com/user/") ? { channel_url: url } : {};
    case "twitch": return { login: url.match(/twitch\.tv\/([^/?]+)/)?.[1] ?? handle.replace(/^@/, "") };
    default: return {};
  }
}

const STATUS_TONE: Record<string, string> = { ok: "green", error: "red", running: "amber", never: "neutral" };
const STATUS_LABEL: Record<string, string> = { ok: "Synced", error: "Error", running: "Syncing…", never: "Not synced yet" };
const INTERVALS = [
  { v: 60, l: "Every hour" }, { v: 180, l: "Every 3 hours" }, { v: 360, l: "Every 6 hours" },
  { v: 720, l: "Every 12 hours" }, { v: 1440, l: "Once a day" }, { v: 0, l: "Manual only" },
];
const RESULT_LABEL: Record<string, string> = {
  followers: "followers", subscribers: "subscribers", total_channel_views: "channel views", posts_created: "new posts",
  posts_updated: "posts updated", contacts_created: "new contacts", contacts_updated: "contacts updated",
  live_viewers: "watching live now", deals_created: "new deals", deals_updated: "deals updated", orders_synced: "orders", revenue_synced: "revenue",
};

function summary(r: Integration["last_result"]) {
  return Object.entries(RESULT_LABEL)
    .filter(([k]) => typeof r[k] === "number")
    .map(([k, label]) => `${k === "revenue_synced" ? money(r[k] as number) : num(r[k] as number)} ${label}`)
    .join(" · ");
}

export default function IntegrationsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [items, setItems] = useState<Integration[]>([]);
  const [editing, setEditing] = useState<{ provider: Provider; existing?: Integration; channelId?: number } | null>(null);
  const [params, setParams] = useSearchParams();
  const opened = useRef(false);
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [ebaySetup, setEbaySetup] = useState<Integration | null>(null);
  const loadChannels = useCrm((s) => s.loadChannels);
  const push = useToasts((s) => s.push);

  const load = useCallback(async () => {
    const [p, i] = await Promise.all([api.get<Provider[]>("/integrations/providers"), api.get<Integration[]>("/integrations")]);
    setProviders(p); setItems(i);
  }, []);
  useEffect(() => { load().catch(toastError); }, [load]);

  const run = async (i: Integration, action: "test" | "sync") => {
    setBusy((b) => ({ ...b, [i.id]: action }));
    try {
      if (action === "test") {
        const r = await api.post<{ ok: boolean; message: string }>(`/integrations/${i.id}/test`);
        push(r.message, r.ok ? "success" : "error");
      } else {
        const r = await api.post<Integration>(`/integrations/${i.id}/sync`);
        setItems((list) => list.map((x) => (x.id === r.id ? r : x)));
        push(r.last_status === "ok" ? `${r.name}: sync complete` : r.last_error, r.last_status === "ok" ? "success" : "error");
        await loadChannels();
      }
    } catch (e) { toastError(e); } finally { setBusy((b) => { const n = { ...b }; delete n[i.id]; return n; }); }
  };

  const remove = async (i: Integration) => {
    if (!confirm(`Disconnect ${i.name}? Synced contacts, deals and posts stay in the CRM.`)) return;
    try { await api.del(`/integrations/${i.id}`); setItems((l) => l.filter((x) => x.id !== i.id)); } catch (e) { toastError(e); }
  };

  useEffect(() => {
    const key = params.get("provider");
    const p = providers.find((x) => x.key === key);
    if (!p || opened.current) return;
    opened.current = true;
    const ch = Number(params.get("channel")) || undefined;
    setEditing({ provider: p, channelId: ch });
    setParams({}, { replace: true });
  }, [providers, params, setParams]);

  const byKey = Object.fromEntries(providers.map((p) => [p.key, p]));

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Integrations</h1><p className="muted">Connect your platforms. Followers, posts, customers and sales sync in automatically.</p></div>
      </header>

      <section className="integration-grid">
        {providers.map((p) => {
          const count = items.filter((i) => i.provider === p.key).length;
          return (
            <article key={p.key} className="card provider-card">
              <div className="row-between"><strong>{p.name}</strong>{count > 0 && <Badge tone="green">{count} connected</Badge>}</div>
              <p className="muted small">{p.summary}</p>
              <ul className="small sync-list">{p.syncs.map((s) => <li key={s}>{s}</li>)}</ul>
              <button className="btn btn-primary btn-sm" onClick={() => setEditing({ provider: p })}>
                {count ? `+ Connect another` : `Connect ${p.name}`}
              </button>
            </article>
          );
        })}
      </section>

      <section className="card">
        <h3>Connections</h3>
        {items.length === 0 ? <Empty title="Nothing connected yet">Pick a platform above to get started.</Empty> : (
          <div className="integration-list">
            {items.map((i) => {
              const p = byKey[i.provider];
              const s = summary(i.last_result);
              return (
                <div key={i.id} className="integration-row" data-testid={`integration-${i.id}`}>
                  <div className="integration-main">
                    <div className="row">
                      <strong>{i.name}</strong>
                      <Badge tone={STATUS_TONE[busy[i.id] === "sync" ? "running" : i.last_status]}>
                        {STATUS_LABEL[busy[i.id] === "sync" ? "running" : i.last_status]}
                      </Badge>
                      {!i.enabled && <Badge>Paused</Badge>}
                    </div>
                    <div className="muted small">
                      {p?.name ?? i.provider} → channel “{i.channel_name ?? "—"}” · last sync {dateTime(i.last_sync_at)} ·{" "}
                      {INTERVALS.find((x) => x.v === i.sync_interval_minutes)?.l ?? `every ${i.sync_interval_minutes} min`}
                    </div>
                    {s && <div className="small">{s}</div>}
                    {!i.secrets_ok && <div className="error-box small">Saved credentials can't be read (the SECRET_KEY changed). Click Edit and re-enter them.</div>}
                    {i.last_status === "error" && i.last_error && <div className="error-box small">{i.last_error}</div>}
                    {(i.last_result.warnings ?? []).map((w) => <div key={w} className="warn-box small">{w}</div>)}
                  </div>
                  <div className="row integration-actions">
                    <button className="btn btn-sm" disabled={!!busy[i.id]} onClick={() => run(i, "test")}>{busy[i.id] === "test" ? "Testing…" : "Test"}</button>
                    <button className="btn btn-sm btn-primary" disabled={!!busy[i.id]} onClick={() => run(i, "sync")}>{busy[i.id] === "sync" ? "Syncing…" : "Sync now"}</button>
                    {i.provider === "ebay" && (
                      <button className={`btn btn-sm ${i.saved_secrets.includes("refresh_token") ? "" : "btn-primary"}`} onClick={() => setEbaySetup(i)}>
                        {i.saved_secrets.includes("refresh_token") ? "eBay setup" : "Finish eBay setup"}
                      </button>
                    )}
                    {p && <button className="btn btn-sm" onClick={() => setEditing({ provider: p, existing: i })}>Edit</button>}
                    <button className="btn btn-sm btn-danger" onClick={() => remove(i)}>Disconnect</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {editing && (
        <ConnectForm provider={editing.provider} existing={editing.existing} channelId={editing.channelId} onClose={() => setEditing(null)}
          onSaved={async (saved, isNew) => {
            setEditing(null);
            setItems((l) => (l.some((x) => x.id === saved.id) ? l.map((x) => (x.id === saved.id ? saved : x)) : [...l, saved]));
            await loadChannels();
            if (isNew && saved.provider === "ebay") {
              push(`${saved.name} saved. Finish the eBay setup steps next.`, "info");
              setEbaySetup(saved);
            } else if (isNew) {
              push(`${saved.name} saved. Running first sync…`, "info");
              await run(saved, "sync");
            }
          }} />
      )}
      {ebaySetup && (
        <EbaySetup integ={ebaySetup} onClose={() => setEbaySetup(null)}
          onChange={(u) => { setItems((l) => l.map((x) => (x.id === u.id ? u : x))); setEbaySetup(u); }}
          onSignedIn={async (u) => { setEbaySetup(null); push("eBay connected. Pulling your orders…", "success"); await run(u, "sync"); }} />
      )}
    </div>
  );
}

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn btn-sm" onClick={() => {
      const ok = () => { setDone(true); setTimeout(() => setDone(false), 1500); };
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(ok).catch(() => window.prompt("Copy this:", text));
      else window.prompt("Copy this:", text);   // plain-http LAN pages can't use the clipboard API
    }}>{done ? "Copied" : "Copy"}</button>
  );
}

function EbaySetup({ integ, onClose, onChange, onSignedIn }: {
  integ: Integration; onClose: () => void; onChange: (i: Integration) => void; onSignedIn: (i: Integration) => void;
}) {
  const [endpoint, setEndpoint] = useState(integ.config.deletion_endpoint ?? "");
  const [ruName, setRuName] = useState(integ.config.ru_name ?? "");
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState("");
  const signedIn = integ.saved_secrets.includes("refresh_token");
  const token = integ.config.verification_token ?? "";

  const save = async (values: Record<string, string>, what: string) => {
    setBusy(what);
    try { onChange(await api.patch<Integration>(`/integrations/${integ.id}`, { values })); useToasts.getState().push("Saved", "success"); }
    catch (e) { toastError(e); } finally { setBusy(""); }
  };
  const openEbay = async () => {
    setBusy("open");
    try {
      if (ruName.trim() !== (integ.config.ru_name ?? "")) onChange(await api.patch<Integration>(`/integrations/${integ.id}`, { values: { ru_name: ruName.trim() } }));
      const { url } = await api.get<{ url: string }>(`/integrations/${integ.id}/ebay/authorize`);
      window.open(url, "_blank", "noopener");
    } catch (e) { toastError(e); } finally { setBusy(""); }
  };
  const finish = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("finish");
    try { onSignedIn(await api.post<Integration>(`/integrations/${integ.id}/ebay/connect`, { pasted })); }
    catch (err) { toastError(err); } finally { setBusy(""); }
  };

  return (
    <Modal title="eBay setup" onClose={onClose} wide footer={<button type="button" className="btn" onClick={onClose}>Close</button>}>
      <div className="ebay-setup">
        <section className="ebay-step">
          <h3>1. Account-deletion notices <span className="muted small">(eBay requires this once)</span></h3>
          <p className="small">Because the CRM saves buyer details, eBay needs a public https address where it can tell the CRM
            when a buyer closes their account (the CRM then deletes that buyer's data). The README section
            “eBay account-deletion notices” shows the one Tailscale command that creates this address on your server.</p>
          <Field label="Notification endpoint URL" hint="Paste this same URL on eBay's Marketplace Account Deletion page.">
            <div className="row">
              <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://mserver.your-tailnet.ts.net/api/ebay/account-deletion" />
              <button type="button" className="btn btn-sm" disabled={busy === "endpoint" || !endpoint.trim().startsWith("https://")}
                onClick={() => save({ deletion_endpoint: endpoint.trim() }, "endpoint")}>Save</button>
              {integ.config.deletion_endpoint && <a className="btn btn-sm" href={integ.config.deletion_endpoint} target="_blank" rel="noreferrer">Check ↗</a>}
            </div>
          </Field>
          <Field label="Verification token" hint="Paste this on eBay's page too. Then click Save there; eBay checks the URL right away.">
            <div className="row"><code className="token-box" data-testid="ebay-token">{token}</code><Copy text={token} /></div>
          </Field>
          <p className="muted small">“Check” should open a page that says the endpoint is reachable. If it doesn't load, the Tailscale step isn't working yet.</p>
        </section>

        <section className="ebay-step">
          <h3>2. RuName</h3>
          <p className="small">On developer.ebay.com click <b>User Tokens</b> next to your Production keyset → “Get a Token from eBay via Your Application” →
            <b> Add eBay Redirect URL</b>. Enter a privacy policy URL (your website is fine), tick <b>OAuth</b>, Save, and copy the RuName it shows.</p>
          <div className="row">
            <input value={ruName} onChange={(e) => setRuName(e.target.value)} placeholder="Your_Name-YourName-Onesho-abcdefg" />
            <button type="button" className="btn btn-sm" disabled={busy === "ru" || !ruName.trim()} onClick={() => save({ ru_name: ruName.trim() }, "ru")}>Save</button>
          </div>
        </section>

        <section className="ebay-step">
          <h3>3. Sign in with eBay {signedIn && <Badge tone="green">Signed in</Badge>}</h3>
          {signedIn && integ.config.refresh_expires_at && <p className="muted small">Sign-in is good until {dateTime(integ.config.refresh_expires_at)}. Do this step again any time to renew it.</p>}
          <p className="small">Click the button, sign in to eBay and click <b>Agree</b>. eBay then shows a “thank you” page.
            Copy the <b>whole address</b> from your browser's address bar on that page and paste it below within 5 minutes.</p>
          <button type="button" className="btn btn-primary" disabled={!ruName.trim() || busy === "open"} onClick={openEbay}>Open eBay sign-in ↗</button>
          <form onSubmit={finish} className="ebay-paste">
            <textarea rows={3} value={pasted} onChange={(e) => setPasted(e.target.value)}
              placeholder="https://signin.ebay.com/...&code=v%5E1.1%23i%5E1..." data-testid="ebay-paste" />
            <button type="submit" className="btn btn-primary" disabled={!pasted.trim() || busy === "finish"}>{busy === "finish" ? "Connecting…" : "Finish sign-in"}</button>
          </form>
        </section>
      </div>
    </Modal>
  );
}

function ConnectForm({ provider, existing, channelId: presetChannel, onClose, onSaved }: {
  provider: Provider; existing?: Integration; channelId?: number; onClose: () => void; onSaved: (i: Integration, isNew: boolean) => void;
}) {
  const channels = useCrm((s) => s.channels);
  const preset = channels.find((c) => c.id === presetChannel);
  const [name, setName] = useState(existing?.name ?? preset?.name ?? provider.name);
  const [channelId, setChannelId] = useState<number | "">(existing?.channel_id ?? preset?.id ?? "");
  const [interval, setIntervalMin] = useState(existing?.sync_interval_minutes ?? 360);
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(provider.fields.map((f) => [f.key, f.secret ? "" : existing?.config[f.key] ?? prefill(provider.key, preset)[f.key] ?? f.default])));
  const [saving, setSaving] = useState(false);
  const [showSteps, setShowSteps] = useState(!existing);
  const matching = channels.filter((c) => c.platform === provider.platform || c.id === channelId);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { name, channel_id: channelId === "" ? null : channelId, values, enabled, sync_interval_minutes: interval };
      const saved = existing
        ? await api.patch<Integration>(`/integrations/${existing.id}`, body)
        : await api.post<Integration>("/integrations", { provider: provider.key, ...body });
      onSaved(saved, !existing);
    } catch (err) { toastError(err); } finally { setSaving(false); }
  };

  return (
    <Modal title={existing ? `Edit ${existing.name}` : `Connect ${provider.name}`} onClose={onClose} wide
      footer={<>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="submit" form="connect-form" className="btn btn-primary" disabled={saving}>{saving ? "Saving…" : existing ? "Save" : "Connect & sync"}</button>
      </>}>
      <div className="steps-box">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowSteps(!showSteps)}>
          {showSteps ? "▾" : "▸"} How to get these details
        </button>
        {showSteps && (
          <>
            <ol className="small">{provider.steps.map((s) => <li key={s}>{s}</li>)}</ol>
            <a className="small" href={provider.docs_url} target="_blank" rel="noreferrer">Official docs ↗</a>
          </>
        )}
      </div>
      <form id="connect-form" className="form-grid" onSubmit={submit}>
        <Field label="Connection name"><input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} /></Field>
        <Field label="Save data to channel" hint="Followers and posts are attached to this channel.">
          <select value={channelId} onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Create a new “{name || provider.name}” channel</option>
            {(matching.length ? matching : channels).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        {provider.fields.map((f) => {
          const saved = existing?.saved_secrets.includes(f.key);
          return (
            <Field key={f.key} label={`${f.label}${f.required ? "" : " (optional)"}`} hint={f.help}>
              {f.kind === "select" ? (
                <select value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                  {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input type={f.secret ? "password" : "text"} autoComplete="off" value={values[f.key]}
                  placeholder={saved ? "•••••• saved (leave blank to keep)" : f.placeholder}
                  required={f.required && !(f.secret && saved)}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
              )}
            </Field>
          );
        })}
        <Field label="Automatic sync">
          <select value={interval} onChange={(e) => setIntervalMin(Number(e.target.value))}>
            {INTERVALS.map((x) => <option key={x.v} value={x.v}>{x.l}</option>)}
          </select>
        </Field>
        <label className="row small"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
      </form>
      <p className="muted small">Secrets are encrypted in your CRM's database and never shown again after saving.</p>
    </Modal>
  );
}
