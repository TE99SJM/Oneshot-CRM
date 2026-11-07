import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { toastError, useToasts } from "../store/toastStore";
import type { Integration, OAuthInfo } from "../types";
import { Modal } from "./ui";

const FUNNEL_CMD = "sudo tailscale funnel --bg --set-path=/api/oauth http://127.0.0.1:3050/api/oauth";

const PORTAL: Record<string, { name: string; url: string; where: string }> = {
  tiktok: {
    name: "TikTok for Developers", url: "https://developers.tiktok.com/apps",
    where: "your app → Products → Login Kit → Redirect URI (Web)",
  },
  tiktok_shop: {
    name: "TikTok Shop Partner Center", url: "https://partner.tiktokshop.com/",
    where: "App & Service → your app → Basic information → Redirect URL",
  },
};

export const isSignedIn = (i: Integration) => i.saved_secrets.includes("refresh_token") || i.saved_secrets.includes("access_token");

/** Sign-in for TikTok and TikTok Shop: save the public return address, sign in, come back automatically. */
export function AppSignIn({ integ, onClose, onChange }: { integ: Integration; onClose: () => void; onChange: (i: Integration) => void }) {
  const [info, setInfo] = useState<OAuthInfo | null>(null);
  const [host, setHost] = useState("");
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState("");
  const [waiting, setWaiting] = useState(false);
  const push = useToasts((s) => s.push);
  const portal = PORTAL[integ.provider];

  useEffect(() => {
    api.get<OAuthInfo>(`/integrations/${integ.id}/oauth`).then((r) => {
      setInfo(r);
      const src = r.saved || r.suggested;
      setHost(src ? new URL(src).origin : "");
    }).catch(toastError);
  }, [integ.id]);

  // after "Sign in", watch for the other tab to finish
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => {
      try {
        const r = await api.get<OAuthInfo>(`/integrations/${integ.id}/oauth`);
        if (r.signed_in) {
          setWaiting(false); setInfo(r);
          onChange(await api.get<Integration>(`/integrations/${integ.id}`));
          push(`${r.name}: signed in${r.account ? ` as ${r.account}` : ""}.`, "success");
        }
      } catch { /* keep waiting */ }
    }, 3000);
    const stop = setTimeout(() => setWaiting(false), 10 * 60 * 1000);
    return () => { clearInterval(t); clearTimeout(stop); };
  }, [waiting, integ.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!info) return <Modal title="Sign in" onClose={onClose}><p className="muted">Loading…</p></Modal>;

  const cleanHost = host.trim().replace(/\/+$/, "").replace(/^(?!https?:\/\/)/, "https://").replace(/^(https?:\/\/[^/]+).*$/, "$1");
  const callback = host.trim() ? `${cleanHost}${info.callback_path}` : "";
  const isIp = /^(https?:\/\/)?\d+\.\d+\.\d+\.\d+/.test(host.trim());
  const unsaved = info.saved !== callback;
  const copy = (v: string) => navigator.clipboard?.writeText(v).then(() => push("Copied.", "success"), () => push(v, "info"));

  const save = async () => {
    setBusy("save");
    try { setInfo(await api.put<OAuthInfo>(`/integrations/${integ.id}/oauth/redirect`, { redirect_uri: callback })); push("Return address saved.", "success"); }
    catch (e) { toastError(e); } finally { setBusy(""); }
  };
  const open = async () => {
    setBusy("open");
    const win = window.open("about:blank", "_blank");
    try {
      const { url } = await api.get<{ url: string }>(`/integrations/${integ.id}/oauth/authorize`, { return_to: window.location.origin });
      if (win) win.location.href = url; else window.location.href = url;
      setWaiting(true);
    } catch (e) { win?.close(); toastError(e); } finally { setBusy(""); }
  };
  const finish = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("finish");
    try {
      const r = await api.post<{ integration: Integration; oauth: OAuthInfo }>(`/integrations/${integ.id}/oauth/connect`, { pasted });
      setInfo(r.oauth); onChange(r.integration); setPasted(""); setWaiting(false);
      push(`${r.oauth.name}: signed in${r.oauth.account ? ` as ${r.oauth.account}` : ""}.`, "success");
    } catch (err) { toastError(err); } finally { setBusy(""); }
  };
  const signOut = async () => {
    if (!confirm(`Sign out of ${info.name}? Synced data stays in the CRM.`)) return;
    try { const r = await api.post<{ integration: Integration; oauth: OAuthInfo }>(`/integrations/${integ.id}/oauth/sign-out`); setInfo(r.oauth); onChange(r.integration); }
    catch (e) { toastError(e); }
  };

  return (
    <Modal title={`${info.name}: sign in`} onClose={onClose} wide footer={<button className="btn" onClick={onClose}>Done</button>}>
      <div className="ebay-setup" data-testid="app-signin">
        {info.signed_in && (
          <div className="callout row-between">
            <span>Signed in{info.account ? <> as <b>{info.account}</b></> : ""}. Click <b>Sync now</b> on the connection to pull data.</span>
            <button className="btn btn-sm btn-danger" onClick={signOut}>Sign out</button>
          </div>
        )}
        {info.missing_scopes && (
          <div className="warn-box small">Your app didn't grant: <b>{info.missing_scopes}</b>. Turn those scopes on in {portal.name}, then sign in again.</div>
        )}
        <section className="ebay-step">
          <h3>1. Return address</h3>
          <p className="small">{info.name} only sends sign-ins back to a named <b>https</b> address, never an IP address like <code>{window.location.host}</code>.
            Your server's Tailscale Funnel address works. If you already did this for YouTube or eBay, skip the command.</p>
          <div className="row code-row small"><code>{FUNNEL_CMD}</code><button type="button" className="btn btn-sm" onClick={() => copy(FUNNEL_CMD)}>Copy</button></div>
          <div className="row">
            <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="https://mserver.your-tailnet.ts.net" data-testid="app-host" />
            <button type="button" className="btn btn-sm btn-primary" disabled={!host.trim() || isIp || busy === "save" || !unsaved} onClick={save} data-testid="app-save-redirect">
              {unsaved ? "Save" : "Saved ✓"}</button>
          </div>
          {isIp && <span className="text-red small">That's an IP address. Use the <b>.ts.net</b> name instead.</span>}
          {callback && !isIp && (
            <div className="small">Copy this into <a href={portal.url} target="_blank" rel="noreferrer">{portal.name}</a> → {portal.where}:
              <div className="row code-row"><code data-testid="app-callback">{callback}</code><button type="button" className="btn btn-sm" onClick={() => copy(callback)}>Copy</button></div>
            </div>
          )}
        </section>
        <section className="ebay-step">
          <h3>2. Sign in</h3>
          <p className="small">Sign in with the account you want to connect and approve the access. You come straight back here and the connection turns on.
            {integ.provider === "tiktok" && <> Until TikTok reviews your app, only accounts you add as test users in the developer portal can sign in.</>}</p>
          <button type="button" className="btn btn-primary" disabled={unsaved || busy === "open"} onClick={open} data-testid="app-open">
            {info.signed_in ? "Sign in again" : `Sign in with ${info.name}`} ↗</button>
          {unsaved && <span className="small muted"> Save the return address first.</span>}
          {waiting && <div className="small muted">Waiting for {info.name}… finish in the other tab. This window updates by itself.</div>}
          <details className="small">
            <summary>Didn't come back to the CRM? Paste the address instead</summary>
            <form onSubmit={finish} className="ebay-paste">
              <textarea rows={3} value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder={`${callback || "https://…ts.net/api/oauth/…/callback"}?code=...&state=...`} data-testid="app-paste" />
              <button className="btn btn-primary" disabled={!pasted.trim() || busy === "finish"}>{busy === "finish" ? "Connecting…" : "Finish sign-in"}</button>
            </form>
          </details>
        </section>
      </div>
    </Modal>
  );
}
