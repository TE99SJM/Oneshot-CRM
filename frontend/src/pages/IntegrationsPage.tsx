import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AppSignIn, isSignedIn } from "../components/AppSignIn";
import { api } from "../api/client";
import { Badge, Empty, Field, Modal } from "../components/ui";
import { BookmarkLink, rumbleBookmarkCode } from "../components/RumbleBookmark";
import { dateTime, money, num, parseUtc } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { Channel, Integration, Provider, SchedulerStatus } from "../types";

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
  { v: 15, l: "Every 15 minutes" }, { v: 30, l: "Every 30 minutes" }, { v: 60, l: "Every hour" }, { v: 180, l: "Every 3 hours" }, { v: 360, l: "Every 6 hours" },
  { v: 720, l: "Every 12 hours" }, { v: 1440, l: "Once a day" }, { v: 0, l: "Manual only" },
];
const RESULT_LABEL: Record<string, string> = {
  followers: "followers", subscribers: "subscribers", total_channel_views: "channel views", total_views: "lifetime views", videos_read: "videos read", posts_created: "new posts",
  posts_updated: "posts updated", contacts_created: "new contacts", contacts_updated: "contacts updated",
  live_viewers: "watching live now", deals_created: "new deals", deals_updated: "deals updated", orders_synced: "orders", revenue_synced: "revenue",
  likes: "total likes", products: "products", products_live: "live products", conversations: "buyer chats", messages_synced: "new messages",
  site_visitors_30d: "site visitors in the last 30 days",
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
  const [ytSetup, setYtSetup] = useState<Integration | null>(null);
  const [rumbleHelp, setRumbleHelp] = useState(false);
  const [signIn, setSignIn] = useState<Integration | null>(null);
  const [syncAfterSignIn, setSyncAfterSignIn] = useState("");
  const loadChannels = useCrm((s) => s.loadChannels);
  const push = useToasts((s) => s.push);

  const load = useCallback(async () => {
    const [p, i] = await Promise.all([api.get<Provider[]>("/integrations/providers"), api.get<Integration[]>("/integrations")]);
    setProviders(p); setItems(i);
  }, []);
  useEffect(() => { load().catch(toastError); }, [load]);
  // Keep "last sync" fresh while the page is open: background syncs happen on the server.
  const [sched, setSched] = useState<SchedulerStatus | null>(null);
  useEffect(() => {
    const tick = () => {
      api.get<Integration[]>("/integrations").then(setItems).catch(() => undefined);
      api.get<SchedulerStatus>("/integrations/scheduler").then(setSched).catch(() => undefined);
    };
    tick();
    const t = setInterval(tick, 60000);
    return () => clearInterval(t);
  }, []);

  // Google's automatic return lands here: /integrations?youtube_posting=connected|error
  useEffect(() => {
    const yp = params.get("youtube_posting");
    if (!yp) return;
    if (yp === "connected") push(`YouTube posting is on${params.get("channel") ? ` for ${params.get("channel")}` : ""}.`, "success");
    else push(params.get("message") || "YouTube sign-in didn't finish.", "error");
    const next = new URLSearchParams(params);
    ["youtube_posting", "channel", "message"].forEach((k) => next.delete(k));
    setParams(next, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // TikTok / TikTok Shop sign-in returns here: /integrations?tiktok_signin=connected|error (or tiktok_shop_signin=)
  useEffect(() => {
    for (const key of ["tiktok", "tiktok_shop"]) {
      const v = params.get(`${key}_signin`);
      if (!v) continue;
      const name = key === "tiktok" ? "TikTok" : "TikTok Shop";
      if (v === "connected") { push(`${name}: signed in${params.get("account") ? ` as ${params.get("account")}` : ""}. Pulling your data…`, "success"); setSyncAfterSignIn(key); }
      else push(params.get("message") || `${name} sign-in didn't finish.`, "error");
      const next = new URLSearchParams(params);
      [`${key}_signin`, "account", "message"].forEach((k) => next.delete(k));
      setParams(next, { replace: true });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!syncAfterSignIn || !items.length) return;
    const todo = items.filter((i) => i.provider === syncAfterSignIn && isSignedIn(i) && (i.provider === "tiktok_shop" || i.last_status !== "ok"));
    setSyncAfterSignIn("");
    todo.forEach((i) => run(i, "sync"));
  }, [items, syncAfterSignIn]); // eslint-disable-line react-hooks/exhaustive-deps

  // The Rumble "Send to CRM" bookmark lands here: /integrations?rumble_import=1#d=<videos JSON>
  useEffect(() => {
    if (!params.get("rumble_import")) return;
    const raw = new URLSearchParams(window.location.hash.slice(1)).get("d");
    window.history.replaceState(null, "", "/integrations");
    setParams({}, { replace: true });
    if (!raw) return;
    (async () => {
      try {
        const body = JSON.parse(raw);
        const r = await api.post<{ imported: number; total_views: number; integration: Integration }>("/integrations/rumble/import", body);
        setItems((l) => l.map((x) => (x.id === r.integration.id ? r.integration : x)));
        push(`Rumble: imported ${num(r.imported)} videos · ${num(r.total_views)} lifetime views`, "success");
        await loadChannels();
      } catch (e) { toastError(e); }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    const editId = Number(params.get("edit"));
    const existing = items.find((i) => i.id === editId);
    const key = params.get("provider");
    const p = providers.find((x) => x.key === (existing?.provider ?? key));
    if (!p || opened.current) return;
    opened.current = true;
    const ch = Number(params.get("channel")) || undefined;
    setEditing({ provider: p, existing, channelId: ch });
    setParams({}, { replace: true });
  }, [providers, items, params, setParams]);

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

      <section className="card connections-card">
        <h3>Connections</h3>
        <SchedulerLine s={sched} />
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
                      {i.enabled && i.next_sync_at && <> · next {until(i.next_sync_at)}</>}
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
                    {i.provider === "youtube" && (
                      <button className="btn btn-sm" onClick={() => setYtSetup(i)} data-testid="yt-posting">
                        {i.saved_secrets.includes("refresh_token") ? "Posting: on" : "Set up posting"}
                      </button>
                    )}
                    {(i.provider === "tiktok" || i.provider === "tiktok_shop") && (
                      <button className={`btn btn-sm ${isSignedIn(i) ? "" : "btn-primary"}`} onClick={() => setSignIn(i)} data-testid="app-signin-open">
                        {isSignedIn(i) ? "Signed in" : "Sign in"}
                      </button>
                    )}
                    {i.provider === "rumble" && (
                      <button className="btn btn-sm" onClick={() => setRumbleHelp(true)} data-testid="rumble-bookmark-open">Send to CRM bookmark</button>
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
            } else if (isNew && (saved.provider === "tiktok" || saved.provider === "tiktok_shop")) {
              push(`${saved.name} saved. Sign in next.`, "info");
              setSignIn(saved);
            } else if (isNew) {
              push(`${saved.name} saved. Running first sync…`, "info");
              await run(saved, "sync");
            }
          }} />
      )}
      {ytSetup && (
        <YoutubePosting integ={ytSetup} onClose={() => setYtSetup(null)}
          onChange={(u) => { setItems((l) => l.map((x) => (x.id === u.id ? u : x))); setYtSetup(u); }} />
      )}
      {signIn && (
        <AppSignIn integ={signIn} onClose={() => setSignIn(null)}
          onChange={(u) => {
            setItems((l) => l.map((x) => (x.id === u.id ? u : x)));
            const wasIn = isSignedIn(signIn);
            setSignIn(u);
            if (!wasIn && isSignedIn(u)) run(u, "sync");
          }} />
      )}
      {rumbleHelp && <RumbleBookmarkHelp onClose={() => setRumbleHelp(false)} />}
      {ebaySetup && (
        <EbaySetup integ={ebaySetup} onClose={() => setEbaySetup(null)}
          onChange={(u) => { setItems((l) => l.map((x) => (x.id === u.id ? u : x))); setEbaySetup(u); }}
          onSignedIn={async (u) => { setEbaySetup(null); push("eBay connected. Pulling your orders…", "success"); await run(u, "sync"); }} />
      )}
    </div>
  );
}

function RumbleBookmarkHelp({ onClose }: { onClose: () => void }) {
  const href = rumbleBookmarkCode(window.location.origin);
  return (
    <Modal title="Rumble views: Send to CRM bookmark" onClose={onClose} wide>
      <p className="small">The CRM tries to read your video views from your public Rumble channel page on every sync. If Rumble's
        anti-bot check blocks your server, this bookmark does the same job from your own browser in about 10 seconds.</p>
      <div className="steps-box"><ol className="small">
        <li>Show your bookmarks bar: press <strong>Ctrl + Shift + B</strong> in Chrome, Edge or Opera.</li>
        <li>Drag this button onto the bookmarks bar: <BookmarkLink href={href}>Send to CRM</BookmarkLink></li>
        <li>Go to your Rumble channel page (for example <span className="mono">rumble.com/c/YourChannel</span>) and click the <strong>Send to CRM</strong> bookmark.</li>
        <li>It reads your videos pages (the tab title shows the progress), then opens this CRM and imports the views, likes and comments.</li>
      </ol></div>
      <p className="small muted">Can't drag? Right-click the bookmarks bar → Add page, name it “Send to CRM”, and paste this as the URL:</p>
      <div className="row"><input readOnly value={href} className="mono small" style={{ flex: 1 }} onFocus={(e) => e.target.select()} aria-label="Bookmark code" /><Copy text={href} /></div>
      <p className="small muted">The bookmark only sends data to this CRM address ({window.location.origin}). If you open the CRM from a different address, make the bookmark again from there.</p>
    </Modal>
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

type YtRedirect = { saved: string; loopback: string; callback_path: string; suggested: string };

function YoutubePosting({ integ, onClose, onChange }: { integ: Integration; onClose: () => void; onChange: (i: Integration) => void }) {
  const [clientId, setClientId] = useState(integ.config.oauth_client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState("");
  const [redir, setRedir] = useState<YtRedirect | null>(null);
  const [mode, setMode] = useState<"auto" | "paste">("auto");
  const [host, setHost] = useState("");
  const [waiting, setWaiting] = useState(false);
  const push = useToasts((s) => s.push);
  const signedIn = integ.saved_secrets.includes("refresh_token");
  const hasSecret = integ.saved_secrets.includes("oauth_client_secret");

  useEffect(() => {
    api.get<YtRedirect>(`/integrations/${integ.id}/youtube/redirect`).then((r) => {
      setRedir(r);
      const auto = r.saved !== r.loopback;
      setMode(auto || !signedIn ? "auto" : "paste");   // already signed in by copy and paste: leave as is
      const src = auto ? r.saved : r.suggested;
      setHost(src ? new URL(src).origin : "");
    }).catch(toastError);
  }, [integ.id]);

  // after "Open Google sign-in" in automatic mode, watch for the sign-in to finish in the other tab
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => {
      try {
        const u = await api.get<Integration>(`/integrations/${integ.id}`);
        if (u.saved_secrets.includes("refresh_token")) {
          setWaiting(false); onChange(u);
          push(`YouTube posting is on${u.config.upload_channel_title ? ` for ${u.config.upload_channel_title}` : ""}.`, "success");
        }
      } catch { /* keep waiting */ }
    }, 3000);
    const stop = setTimeout(() => setWaiting(false), 10 * 60 * 1000);
    return () => { clearInterval(t); clearTimeout(stop); };
  }, [waiting, integ.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const savedAuto = !!redir && redir.saved !== redir.loopback;
  const callback = host.trim() ? `${host.trim().replace(/\/+$/, "").replace(/^(?!https?:\/\/)/, "https://").replace(/^(https?:\/\/[^/]+).*$/, "$1")}${redir?.callback_path ?? "/api/oauth/youtube/callback"}` : "";
  const unsaved = mode === "auto" && (!savedAuto || redir?.saved !== callback);
  const isIp = /^(https?:\/\/)?\d+\.\d+\.\d+\.\d+/.test(host.trim());

  const saveRedirect = async (value: string) => {
    setBusy("redirect");
    try {
      const r = await api.put<YtRedirect>(`/integrations/${integ.id}/youtube/redirect`, { redirect_uri: value });
      setRedir(r);
      push(value ? "Return address saved." : "Switched to copy and paste.", "success");
    } catch (e) { toastError(e); } finally { setBusy(""); }
  };
  const pickMode = (m: "auto" | "paste") => {
    setMode(m);
    if (m === "paste" && savedAuto) saveRedirect("");
  };
  const copy = (v: string) => navigator.clipboard?.writeText(v).then(() => push("Copied.", "success"), () => push(v, "info"));

  const saveKeys = async () => {
    setBusy("save");
    try {
      const values: Record<string, string> = { oauth_client_id: clientId.trim() };
      if (clientSecret.trim()) values.oauth_client_secret = clientSecret.trim();
      onChange(await api.patch<Integration>(`/integrations/${integ.id}`, { values }));
      setClientSecret("");
      push("Saved.", "success");
    } catch (e) { toastError(e); } finally { setBusy(""); }
  };
  const open = async () => {
    setBusy("open");
    const win = window.open("about:blank", "_blank");
    try {
      const { url, automatic } = await api.get<{ url: string; automatic: boolean }>(`/integrations/${integ.id}/youtube/authorize`,
        { return_to: window.location.origin });
      if (win) win.location.href = url; else window.location.href = url;
      if (automatic) setWaiting(true);
    } catch (e) { win?.close(); toastError(e); } finally { setBusy(""); }
  };
  const finish = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("finish");
    try {
      const u = await api.post<Integration>(`/integrations/${integ.id}/youtube/connect`, { pasted });
      onChange(u); setPasted(""); setWaiting(false);
      push(`YouTube posting is on${u.config.upload_channel_title ? ` for ${u.config.upload_channel_title}` : ""}.`, "success");
    } catch (err) { toastError(err); } finally { setBusy(""); }
  };
  const disconnect = async () => {
    if (!confirm("Turn off YouTube posting for this connection? Stats syncing keeps working.")) return;
    try { onChange(await api.post<Integration>(`/integrations/${integ.id}/youtube/disconnect`)); } catch (e) { toastError(e); }
  };

  const funnelCmd = "sudo tailscale funnel --bg --set-path=/api/oauth http://127.0.0.1:3050/api/oauth";
  return (
    <Modal title="YouTube: set up posting" onClose={onClose} wide footer={<button className="btn" onClick={onClose}>Done</button>}>
      <div className="ebay-setup">
        {signedIn && (
          <div className="callout row-between">
            <span>Posting is on{integ.config.upload_channel_title ? <> for <b>{integ.config.upload_channel_title}</b></> : ""}. Use the Compose page to upload videos.</span>
            <button className="btn btn-sm btn-danger" onClick={disconnect}>Turn off</button>
          </div>
        )}
        <section className="ebay-step">
          <h3>1. How Google sends you back</h3>
          <div className="segmented" role="tablist">
            <button className={mode === "auto" ? "active" : ""} onClick={() => pickMode("auto")} data-testid="yt-mode-auto">Automatic (recommended)</button>
            <button className={mode === "paste" ? "active" : ""} onClick={() => pickMode("paste")} data-testid="yt-mode-paste">Copy and paste</button>
          </div>
          {mode === "auto" ? (
            <div className="small yt-auto">
              <p>Google only sends sign-ins back to a named <b>https</b> address. It refuses IP addresses like <code>{window.location.host}</code>.
                Your server's Tailscale Funnel address works, and only the small <code>/api/oauth</code> sign-in path is shared. The rest of the CRM stays private.</p>
              <ol>
                <li>On the server, run this once (same as you did for eBay):
                  <div className="row code-row"><code data-testid="yt-funnel-cmd">{funnelCmd}</code><button type="button" className="btn btn-sm" onClick={() => copy(funnelCmd)}>Copy</button></div>
                  If it prints a link to turn on Funnel or HTTPS, open it, click Enable and run the command again.
                  Then run <code>tailscale funnel status</code> and copy the <code>https://….ts.net</code> address it shows.</li>
                <li>Paste that address here{redir?.suggested ? " (filled in from your eBay setup)" : ""}:
                  <div className="row">
                    <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="https://mserver.your-tailnet.ts.net" data-testid="yt-host" />
                    <button type="button" className="btn btn-sm btn-primary" disabled={!host.trim() || isIp || busy === "redirect" || !unsaved}
                      onClick={() => saveRedirect(host.trim())} data-testid="yt-save-redirect">{unsaved ? "Save" : "Saved ✓"}</button>
                  </div>
                  {isIp && <span className="text-red">That's an IP address. Google needs the <b>.ts.net</b> name instead.</span>}
                </li>
                {callback && !isIp && (
                  <li>Your Google return address (you'll paste it in Google in step 2):
                    <div className="row code-row"><code data-testid="yt-callback">{callback}</code><button type="button" className="btn btn-sm" onClick={() => copy(callback)}>Copy</button></div>
                  </li>
                )}
              </ol>
            </div>
          ) : (
            <p className="small">Works without any server setup. After signing in, Google opens a page at <code>127.0.0.1</code> that won't load. You copy its address bar and paste it into the CRM.</p>
          )}
        </section>
        <section className="ebay-step">
          <h3>2. Make a Google sign-in app (one time)</h3>
          <ol className="small">
            <li>Go to <a href="https://console.cloud.google.com/auth/overview" target="_blank" rel="noreferrer">console.cloud.google.com → Google Auth Platform</a> and pick the same project as your API key.</li>
            <li>Click <b>Get started</b> (skip if done): any app name, your email, Audience <b>External</b>, your email again, then Create.</li>
            <li>Open <b>Audience</b> and click <b>Publish app</b> → Confirm (status “In production”). Skip this and Google signs you out every 7 days. No review is needed for your own channel.</li>
            {mode === "auto" ? (
              <li>Open <b>Clients</b> → <b>Create client</b> → Application type <b>Web application</b>. Under <b>Authorized redirect URIs</b> click <b>Add URI</b> and paste the return address from step 1. Leave “Authorized JavaScript origins” empty. Click <b>Create</b>, then copy the Client ID and Client secret.
                <div className="muted">Already made a “Desktop app” client? That type can't use this address. Make the new Web application client and paste its ID and secret below; they replace the old ones.</div></li>
            ) : (
              <li>Open <b>Clients</b> → <b>Create client</b> → Application type <b>Desktop app</b> → Create. Copy the Client ID and Client secret.</li>
            )}
          </ol>
        </section>
        <section className="ebay-step">
          <h3>3. Paste the client details</h3>
          <div className="form-grid">
            <Field label="Client ID"><input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="1234-abc.apps.googleusercontent.com" /></Field>
            <Field label="Client secret"><input type="password" autoComplete="off" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)}
              placeholder={hasSecret ? "•••••• saved (leave blank to keep)" : "GOCSPX-..."} /></Field>
          </div>
          <button type="button" className="btn btn-sm" disabled={!clientId.trim() || (!hasSecret && !clientSecret.trim()) || busy === "save"} onClick={saveKeys}>Save</button>
        </section>
        <section className="ebay-step">
          <h3>4. Sign in with the account that owns the channel</h3>
          <p className="small">Google will say <b>“Google hasn't verified this app”</b>. That's expected for your own app: click <b>Advanced</b> → <b>Go to … (unsafe)</b>, tick the boxes, then <b>Continue</b>.{" "}
            {mode === "auto"
              ? <>Google then sends you straight back to the CRM and posting turns on by itself.</>
              : <>At the end your browser opens a page at <code>127.0.0.1</code> that <b>won't load</b>. That's fine: copy the whole address bar and paste it below.</>}</p>
          <button type="button" className="btn btn-primary" disabled={!integ.config.oauth_client_id || !hasSecret || busy === "open" || (mode === "auto" && unsaved)}
            onClick={open} data-testid="yt-open">Open Google sign-in ↗</button>
          {mode === "auto" && unsaved && <span className="small muted"> Save the return address in step 1 first.</span>}
          {waiting && <div className="small muted" data-testid="yt-waiting">Waiting for Google… finish signing in in the other tab. This window updates by itself.</div>}
          <details className="small" open={mode === "paste"}>
            {mode === "auto" && <summary>Page didn't come back to the CRM? Paste its address instead</summary>}
            <form onSubmit={finish} className="ebay-paste">
              <textarea rows={3} value={pasted} onChange={(e) => setPasted(e.target.value)}
                placeholder={mode === "auto" ? `${callback || "https://…ts.net/api/oauth/youtube/callback"}?state=...&code=4/0Ab...` : "http://127.0.0.1/?state=...&code=4/0Ab...&scope=..."} data-testid="yt-paste" />
              <button className="btn btn-primary" disabled={!pasted.trim() || busy === "finish"}>{busy === "finish" ? "Connecting…" : "Finish sign-in"}</button>
            </form>
          </details>
        </section>
      </div>
    </Modal>
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
  const [interval, setIntervalMin] = useState(existing?.sync_interval_minutes ?? provider.default_interval ?? 360);
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
        <Field label="Save data to channel" hint={provider.key === "google_analytics" ? "Visitor totals appear in the dashboard's Site Visitor section." : "Followers and posts are attached to this channel."}>
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
              ) : f.kind === "json_file" ? (
                <input type="file" accept=".json,application/json" required={f.required && !saved}
                  onChange={async (e) => {
                    const input = e.currentTarget;
                    const file = input.files?.[0];
                    setValues((v) => ({ ...v, [f.key]: "" }));
                    if (!file) return;
                    try {
                      if (file.size > 32000) throw new Error("Choose a service-account JSON key smaller than 32 KB.");
                      const text = await file.text();
                      const parsed = JSON.parse(text);
                      if (parsed.type !== "service_account" || !parsed.private_key || !parsed.client_email)
                        throw new Error("Choose a service-account JSON key, not an OAuth client JSON file.");
                      setValues((v) => ({ ...v, [f.key]: text }));
                    } catch (error) { input.value = ""; toastError(error); }
                  }} />
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

function until(s: string) {
  const m = Math.round((parseUtc(s).getTime() - Date.now()) / 60000);
  if (m <= 1) return "within a minute";
  if (m < 60) return `in ${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  return `in ${h} h${r ? ` ${r} min` : ""}`;
}

function ago(s: string | null) {
  if (!s) return "not yet";
  const m = Math.round((Date.now() - parseUtc(s).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
}

/** Shows whether the server's automatic sync is alive, so "it isn't pulling data" is easy to diagnose. */
function SchedulerLine({ s }: { s: SchedulerStatus | null }) {
  if (!s) return null;
  if (!s.enabled) return (
    <div className="warn-box small" data-testid="sched-off">
      Automatic sync is turned off on this server (SYNC_SCHEDULER=false in .env). Remove that line and restart to turn it back on.
    </div>
  );
  if (!s.healthy) return (
    <div className="error-box small" data-testid="sched-stuck">
      Automatic sync looks stuck
      {[s.lanes.stats, s.lanes.sales].filter((l) => l.running_name).map((l) => ` — still busy with “${l.running_name}” for ${Math.round((l.running_seconds ?? 0) / 60)} min`).join("")}.
      Restart the CRM (<code>docker compose restart</code>) and tell me what this box said.
    </div>
  );
  const busy = [s.lanes.stats, s.lanes.sales].filter((l) => l.running_name).map((l) => l.running_name);
  return (
    <p className="muted small" data-testid="sched-ok">
      Automatic sync is on: followers & views every 6 hours, sales & messages every 15 minutes (change per connection with Edit).
      {" "}Last check {ago(s.lanes.stats.last_tick)}{busy.length ? ` · syncing ${busy.join(", ")} now` : ""}.
    </p>
  );
}
