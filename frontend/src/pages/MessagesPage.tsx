import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty } from "../components/ui";
import { dateTime } from "../format";
import { toastError, useToasts } from "../store/toastStore";
import type { ConversationDetail, ConversationRow } from "../types";

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
  useEffect(() => { if (rows && openId === null && rows.length && window.innerWidth > 900) setOpenId(rows[0].id); }, [rows, openId]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <p className="muted">Buyer chats from TikTok Shop, pulled in on every sync. Replies you send here go straight to the buyer in TikTok.</p>
        </div>
        {unread > 0 && <Badge tone="blue">{unread} unread</Badge>}
      </div>
      <div className="toolbar">
        <input className="search" placeholder="Search buyer or message…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={onlyUnread} onChange={(e) => setOnlyUnread(e.target.checked)} /> Unread only</label>
      </div>
      {!rows ? <p className="muted">Loading…</p> : rows.length === 0 ? (
        <Empty title={q || onlyUnread ? "No chats match" : "No messages yet"}>
          Connect TikTok Shop on the <Link to="/integrations">Integrations</Link> page and click Sync. Buyer chats show up here.
        </Empty>
      ) : (
        <div className="inbox">
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
          {openId ? <Thread key={openId} id={openId} onChanged={load} /> : <div className="card inbox-thread muted center">Pick a chat</div>}
        </div>
      )}
    </div>
  );
}

function Thread({ id, onChanged }: { id: number; onChanged: () => void }) {
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
