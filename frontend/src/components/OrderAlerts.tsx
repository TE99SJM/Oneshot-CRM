import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Field } from "./ui";
import { toastError, useToasts } from "../store/toastStore";

type Cfg = {
  enabled: boolean;
  push_enabled: boolean; push_server: string; push_topic: string;
  twilio_enabled: boolean; twilio_sid: string; twilio_from: string; twilio_to: string;
  email_enabled: boolean; email_from: string; email_carrier: string; email_number: string; email_to: string;
  min_total: number; sources: string[]; show_customer: boolean; app_url: string;
};
type Hist = { at: string; kind: string; title: string; results: Record<string, string> };
type Data = {
  config: Cfg; saved_secrets: string[]; gmail_connection: string; email_target: string;
  carriers: { key: string; label: string; domain: string }[]; history: Hist[];
};
const LABEL: Record<string, string> = { push: "Phone push", twilio: "Text (Twilio)", email: "Text by email", none: "Nothing sent" };
const SOURCES = [["square", "Square"], ["ebay", "eBay"], ["tiktok_shop", "TikTok Shop"]];

export default function OrderAlerts() {
  const toast = useToasts((s) => s.push);
  const [data, setData] = useState<Data | null>(null);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [sec, setSec] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [advanced, setAdvanced] = useState(false);

  function apply(d: Data) { setData(d); setCfg(d.config); setSec({}); }
  useEffect(() => { api.get<Data>("/notifications").then(apply).catch(toastError); }, []);
  if (!cfg || !data) return <div className="card"><h3>Order alerts</h3><p className="muted">Loading…</p></div>;

  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg({ ...cfg, [k]: v });
  const has = (k: string) => data.saved_secrets.includes(k);
  const topicUrl = `${(cfg.push_server || "https://ntfy.sh").replace(/\/$/, "")}/${cfg.push_topic}`;

  async function save(quiet = false) {
    const body = { config: { ...cfg, app_url: cfg!.app_url || window.location.origin }, secrets: sec };
    const d = await api.put<Data>("/notifications", body);
    apply(d);
    if (!quiet) toast("Order alerts saved", "success");
    return d;
  }
  async function test(channel?: string) {
    setBusy(channel || "all");
    try {
      await save(true);
      const r = await api.post<{ ok: boolean; results: Record<string, string> }>("/notifications/test", { channel });
      const bad = Object.entries(r.results).filter(([, v]) => v !== "ok");
      if (!bad.length) toast("Test sent. Check your phone.", "success");
      else toast(bad.map(([k, v]) => `${LABEL[k] || k}: ${v}`).join(" · "), "error");
      setData(await api.get<Data>("/notifications"));
    } catch (e) { toastError(e); } finally { setBusy(""); }
  }
  const secretInput = (k: string, placeholder: string) => (
    <input type="password" autoComplete="off" value={sec[k] || ""} onChange={(e) => setSec({ ...sec, [k]: e.target.value })}
      placeholder={has(k) ? "Saved - leave blank to keep" : placeholder} />
  );

  return (
    <div className="card alerts-card" data-testid="order-alerts">
      <div className="row-between wrap">
        <div><h3>Order alerts to my phone</h3>
          <p className="muted small">Get a notification or text the moment a sync finds a new Square, eBay or TikTok Shop order. Sales sync every 15 minutes, so an alert arrives within about 15 minutes of the sale.</p></div>
        <label className="check big-check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Alerts on</label>
      </div>

      <div className={`alert-way ${cfg.push_enabled ? "on" : ""}`}>
        <label className="check big-check"><input type="checkbox" checked={cfg.push_enabled} onChange={(e) => set("push_enabled", e.target.checked)} />
          <span><b>Phone push notification</b> <span className="badge badge-green">Free · recommended</span></span></label>
        <p className="muted small">Pops up on your lock screen just like a text. No account, no API key, works on iPhone and Android.</p>
        <ol className="small steps-list">
          <li>Install the free <b>ntfy</b> app: <a href="https://apps.apple.com/us/app/ntfy/id1625396347" target="_blank" rel="noreferrer">iPhone App Store</a> or <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy" target="_blank" rel="noreferrer">Android Google Play</a>.</li>
          <li>Open it, tap <b>+</b> (Subscribe to topic) and type this topic name exactly:</li>
        </ol>
        <div className="topic-box">
          <code data-testid="push-topic">{cfg.push_topic}</code>
          <button type="button" className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(cfg.push_topic).then(() => toast("Topic copied", "success"))}>Copy</button>
        </div>
        <ol className="small steps-list" start={3}>
          <li>Allow notifications when your phone asks, then tap <b>Send test</b> below.</li>
        </ol>
        <p className="muted small">The topic name works like a password, so keep it private. Anyone who knows it can see your alerts.</p>
        <button type="button" className="link-btn small" onClick={() => setAdvanced(!advanced)}>{advanced ? "Hide" : "Show"} advanced push settings</button>
        {advanced && <div className="grid-2">
          <Field label="Topic name" hint="Letters, numbers, - and _. Change it if it ever leaks."><input value={cfg.push_topic} onChange={(e) => set("push_topic", e.target.value)} /></Field>
          <Field label="ntfy server" hint="Leave as https://ntfy.sh unless you run your own ntfy server"><input value={cfg.push_server} onChange={(e) => set("push_server", e.target.value)} /></Field>
          <Field label="Access token (optional)" hint="Only for a protected topic or your own server">{secretInput("push_token", "tk_…")}</Field>
          <Field label="Topic web page"><a href={topicUrl} target="_blank" rel="noreferrer" className="small">{topicUrl}</a></Field>
        </div>}
        <button type="button" className="btn" disabled={!!busy} onClick={() => test("push")}>{busy === "push" ? "Sending…" : "Send test push"}</button>
      </div>

      <div className={`alert-way ${cfg.twilio_enabled ? "on" : ""}`}>
        <label className="check big-check"><input type="checkbox" checked={cfg.twilio_enabled} onChange={(e) => set("twilio_enabled", e.target.checked)} />
          <span><b>Real text message (SMS) through Twilio</b> <span className="badge">About 1¢ per text</span></span></label>
        <p className="muted small">A real text in your Messages app. You need a paid Twilio account, a toll-free number (about $2/month), and Twilio's free toll-free verification, which takes about 3–5 business days. US carriers block texts from unverified numbers.</p>
        {cfg.twilio_enabled && <div className="grid-2">
          <Field label="Account SID" hint="Twilio Console home page, starts with AC"><input value={cfg.twilio_sid} onChange={(e) => set("twilio_sid", e.target.value)} placeholder="AC…" /></Field>
          <Field label="Auth Token" hint="Next to the Account SID">{secretInput("twilio_token", "Auth Token")}</Field>
          <Field label="From (your Twilio number)"><input inputMode="tel" value={cfg.twilio_from} onChange={(e) => set("twilio_from", e.target.value)} placeholder="+18885550100" /></Field>
          <Field label="Your phone"><input inputMode="tel" value={cfg.twilio_to} onChange={(e) => set("twilio_to", e.target.value)} placeholder="+12185550100" /></Field>
        </div>}
        <button type="button" className="btn" disabled={!!busy || !cfg.twilio_enabled} onClick={() => test("twilio")}>{busy === "twilio" ? "Sending…" : "Send test text"}</button>
      </div>

      <div className={`alert-way ${cfg.email_enabled ? "on" : ""}`}>
        <label className="check big-check"><input type="checkbox" checked={cfg.email_enabled} onChange={(e) => set("email_enabled", e.target.checked)} />
          <span><b>Text through email (Gmail)</b> <span className="badge">Free · some carriers only</span></span></label>
        <p className="muted small">Sends from your Gmail to your carrier's email-to-text address. <b>AT&amp;T, Cricket and T-Mobile have shut this down.</b> Verizon still delivers it, though not always, until 31 March 2027. Google Fi and US Cellular still work. You can also just send the alert to any email address.</p>
        {cfg.email_enabled && <div className="grid-2">
          <Field label="Your carrier">
            <select value={cfg.email_carrier} onChange={(e) => set("email_carrier", e.target.value)}>
              {data.carriers.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </Field>
          {cfg.email_carrier === "custom"
            ? <Field label="Send to this address"><input type="email" value={cfg.email_to} onChange={(e) => set("email_to", e.target.value)} placeholder="you@example.com" /></Field>
            : <Field label="Your phone number" hint={data.email_target ? `Sends to ${data.email_target}` : "10 digits"}><input inputMode="tel" value={cfg.email_number} onChange={(e) => set("email_number", e.target.value)} placeholder="218 555 0100" /></Field>}
          <Field label="Send from Gmail address" hint={data.gmail_connection ? `Leave blank to use your Gmail connection (${data.gmail_connection})` : "Your Gmail address"}>
            <input type="email" value={cfg.email_from} onChange={(e) => set("email_from", e.target.value)} placeholder={data.gmail_connection || "you@gmail.com"} /></Field>
          <Field label="Google app password" hint="16 letters from myaccount.google.com/apppasswords (not your normal password)">{secretInput("gmail_app_password", data.gmail_connection ? "Using your Gmail connection" : "abcd efgh ijkl mnop")}</Field>
        </div>}
        <button type="button" className="btn" disabled={!!busy || !cfg.email_enabled} onClick={() => test("email")}>{busy === "email" ? "Sending…" : "Send test email/text"}</button>
      </div>

      <h4>What to alert on</h4>
      <div className="grid-2">
        <Field label="Only orders of at least ($)" hint="0 = every order">
          <input type="number" min={0} step="0.01" inputMode="decimal" value={cfg.min_total} onChange={(e) => set("min_total", Number(e.target.value))} /></Field>
        <div className="field">
          <span className="field-label">From these stores</span>
          <div className="row wrap store-checks">{SOURCES.map(([k, l]) => (
            <label key={k} className="check"><input type="checkbox" checked={cfg.sources.includes(k)}
              onChange={(e) => set("sources", e.target.checked ? [...cfg.sources, k] : cfg.sources.filter((s) => s !== k))} /> {l}</label>))}</div>
          <span className="field-hint">None ticked = all stores</span>
        </div>
        <label className="check"><input type="checkbox" checked={cfg.show_customer} onChange={(e) => set("show_customer", e.target.checked)} /> Show the customer's name in the alert</label>
        <Field label="CRM link in alerts" hint="Tapping a push alert opens this page. Filled in from this browser's address if blank.">
          <input value={cfg.app_url} onChange={(e) => set("app_url", e.target.value)} placeholder={window.location.origin} /></Field>
      </div>
      <p className="muted small alerts-note">The first sync of a new store connection imports your history without alerting. Orders more than 3 days old never alert. If more than 3 orders arrive at once, you get one summary instead of a flood.</p>

      <div className="row wrap">
        <button type="button" className="btn btn-primary" disabled={!!busy} onClick={() => save().catch(toastError)}>Save alerts</button>
        <button type="button" className="btn" disabled={!!busy} onClick={() => test()}>{busy === "all" ? "Sending…" : "Send test to all turned-on"}</button>
      </div>

      {data.history.length > 0 && <>
        <h4>Recent alerts</h4>
        <ul className="alert-history">
          {data.history.slice(0, 8).map((h, i) => (
            <li key={i}>
              <span className="small muted">{new Date(h.at + "Z").toLocaleString()}</span>
              <span>{h.title}</span>
              <span className="row wrap">{Object.entries(h.results).map(([k, v]) => (
                <span key={k} className={`badge ${v === "ok" ? "badge-green" : "badge-red"}`} title={v}>{LABEL[k] || k}: {v === "ok" ? "sent" : "failed"}</span>))}</span>
              {Object.values(h.results).some((v) => v !== "ok") && <span className="small error-text">{Object.entries(h.results).filter(([, v]) => v !== "ok").map(([k, v]) => `${LABEL[k] || k}: ${v}`).join(" · ")}</span>}
            </li>))}
        </ul>
      </>}
    </div>
  );
}
