import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty } from "../components/ui";
import { dateTime, parseUtc } from "../format";
import { toastError, useToasts } from "../store/toastStore";
import type { ConversationDetail, ConversationRow, MessagesStatus } from "../types";

const SOURCE_LABEL: Record<string, string> = { tiktok_shop: "TikTok Shop" };

export default function MessagesPage() {
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [q, setQ] = useState("");
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (onlyUnread) p.set("unread_only", "true");
    api.get<{ conversations: ConversationRow[]; unread_total: number }>(`/messages?${p}`)
      .then((r) => { setRows(r.conversations); setUnread(r.unread_total); }).catch(toastError);
  }, [q, onlyUnread]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);
  useEffect(() => { const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);   // new chats arrive in the background
  useEffect(() => { if (rows && openId === null && rows.length && window.innerWidth > 900) setOpenId(rows[0].id); }, [rows, openId]);

  return (
    <div className={`page${openId ? " chat-open" : ""}`}>
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <p className="muted">Buyer chats from TikTok Shop, checked every few minutes. Replies you send here go straight to the buyer in TikTok.</p>
        </div>
        {unread > 0 && <Badge tone="blue">{unread} unread</Badge>}
      </div>
      <ChatStatus onChecked={load} />
      <div className="toolbar">
        <input className="search" placeholder="Search buyer or message…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={onlyUnread} onChange={(e) => setOnlyUnread(e.target.checked)} /> Unread only</label>
      </div>
      {!rows ? <p className="muted">Loading…</p> : rows.length === 0 ? (
        <Empty title={q || onlyUnread ? "No chats match" : "No messages yet"}>
          Connect TikTok Shop on the <Link to="/integrations">Integrations</Link> page and click Sync. Buyer chats show up here.
        </Empty>
      ) : (
        <div className={`inbox${openId ? " thread-open" : ""}`}>
          <div className="card inbox-list" data-testid="conv-list">
            {rows.map((c) => (
              <button key={c.id} className={`inbox-row${c.id === openId ? " active" : ""}${c.unread ? " unread" : ""}`} onClick={() => setOpenId(c.id)}>
                <div className="row-tight between">
                  <strong className="ellipsis">{c.title}</strong>
                  <span className="muted small nowrap">{dateTime(c.last_message_at)}</span>
                </div>
                <div className="row-tight between">
                  <span className="muted small ellipsis">{c.last_message}</span>
                  {c.unread > 0 && <span className="pill-count">{c.unread}</span>}
                </div>
                <span className="muted small"><span className="platform-dot p-tiktok" /> {SOURCE_LABEL[c.source] ?? c.source}</span>
              </button>
            ))}
          </div>
          {openId ? <Thread key={openId} id={openId} onChanged={load} onBack={() => setOpenId(null)} /> : <div className="card inbox-thread muted center">Pick a chat</div>}
        </div>
      )}
    </div>
  );
}

function Thread({ id, onChanged, onBack }: { id: number; onChanged: () => void; onBack: () => void }) {
  const [c, setC] = useState<ConversationDetail | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(() => api.get<ConversationDetail>(`/messages/${id}`).then(setC).catch(toastError), [id]);
  useEffect(() => {
    load().then(() => api.post(`/messages/${id}/read`, {}).then(onChanged).catch(() => undefined));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [c?.messages.length]);

  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.post(`/messages/${id}/reply`, { text: text.trim() });
      setText("");
      await load();
      onChanged();
    } catch (e) { toastError(e); } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true);
    try { setC(await api.post<ConversationDetail>(`/messages/${id}/refresh`, {})); useToasts.getState().push("Pulled the latest messages", "success"); }
    catch (e) { toastError(e); } finally { setBusy(false); }
  };

  if (!c) return <div className="card inbox-thread muted">Loading…</div>;
  return (
    <div className="card inbox-thread" data-testid="thread">
      <div className="row between thread-head">
        <button className="back-btn mobile-only" onClick={onBack} data-testid="back-to-chats">‹ Chats</button>
        <div>
          <strong>{c.title}</strong>
          <div className="muted small">{SOURCE_LABEL[c.source] ?? c.source}{c.contact_id ? <> · <Link to={`/contacts?open=${c.contact_id}`}>Open contact</Link></> : null}</div>
        </div>
        <button className="btn btn-sm" disabled={busy} onClick={refresh}>Load full history</button>
      </div>
      <div className="thread-body">
        {c.messages.length === 0 && <p className="muted">No messages saved yet. Click “Load full history”.</p>}
        {c.messages.map((m) => (
          <div key={m.id} className={`bubble ${m.direction === "out" ? "out" : "in"}`}>
            <div className="bubble-text">{m.body || <em>[{m.kind.toLowerCase()}]</em>}</div>
            <div className="bubble-meta">{m.sender_name} · {dateTime(m.sent_at)}</div>
          </div>
        ))}
        <div ref={end} />
      </div>
      {c.can_reply ? (
        <div className="thread-reply">
          <textarea rows={2} maxLength={2000} placeholder="Write a reply…" value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); }} data-testid="reply-box" />
          <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={send}>Send</button>
        </div>
      ) : <p className="muted small thread-reply">{c.reply_note || "Replies are closed for this chat."}</p>}
    </div>
  );
}

function ago(s: string | null) {
  if (!s) return "never";
  const m = Math.round((Date.now() - parseUtc(s).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : dateTime(s);
}

/** One line per TikTok Shop connection: are buyer chats switched on yet, and what to do if not. */
function ChatStatus({ onChecked }: { onChecked: () => void }) {
  const [rows, setRows] = useState<MessagesStatus[] | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.get<MessagesStatus[]>("/messages/status").then(setRows).catch(() => undefined), []);
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);
  const check = async () => {
    setBusy(true);
    try {
      const r = await api.post<(MessagesStatus & { result: { new_messages?: number } })[]>("/messages/check", {});
      setRows(r);
      const n = r.reduce((a, x) => a + (x.result?.new_messages ?? 0), 0);
      useToasts.getState().push(r.some((x) => x.status === "active") ? `Checked — ${n} new message${n === 1 ? "" : "s"}` : "Checked — still waiting on TikTok");
      onChecked();
    } catch (e) { toastError(e); } finally { setBusy(false); }
  };
  if (!rows || rows.length === 0) return null;
  const btn = <button className="btn btn-sm" disabled={busy} onClick={check}>{busy ? "Checking…" : "Check now"}</button>;
  return (
    <div style={{ display: "grid", gap: 8, marginBottom: 12 }} data-testid="chat-status">
      {rows.map((r) => {
        const label = rows.length > 1 ? `${r.name}: ` : "";
        if (r.status === "not_signed_in") return (
          <div key={r.integration_id} className="warn-box">
            {label}TikTok Shop isn't signed in yet. Go to <Link to="/integrations">Integrations</Link> → TikTok Shop → Sign in with TikTok Shop.
          </div>
        );
        if (r.status === "waiting_approval") return (
          <div key={r.integration_id} className="warn-box" data-testid="waiting-approval">
            <strong>{label}Buyer messages are waiting for TikTok to approve your app.</strong> Orders and products still sync normally.
            <ol style={{ margin: "6px 0 6px 18px", padding: 0 }}>
              <li>In TikTok Shop Partner Center open your app → Manage API / scopes, add <strong>Customer Service</strong> and submit for review.</li>
              <li>When TikTok approves it, go to <Link to="/integrations">Integrations</Link> → TikTok Shop → <strong>Sign in with TikTok Shop</strong> again (new permissions only apply after a fresh sign-in).</li>
              <li>That's it — chats start showing up here within a minute. Until then the CRM re-checks once an hour on its own.</li>
            </ol>
            <div className="row-tight between"><span className="small">Last checked {ago(r.checked_at)}{r.error ? ` · TikTok said: ${r.error}` : ""}</span>{btn}</div>
          </div>
        );
        if (r.status === "error") return (
          <div key={r.integration_id} className="warn-box" style={{ background: "var(--red-soft)", color: "var(--red)" }}>
            <div className="row-tight between"><span>{label}Couldn't check buyer messages: {r.error || "unknown error"} (retrying every 15 min)</span>{btn}</div>
          </div>
        );
        return (
          <div key={r.integration_id} className="row-tight between muted small">
            <span>{label}{r.status === "active" ? "Buyer messages on" : "Buyer messages not checked yet"} · checking {r.every_minutes ? `every ${r.every_minutes} min` : "with each full sync"} · last checked {ago(r.checked_at)}</span>
            {btn}
          </div>
        );
      })}
    </div>
  );
}
