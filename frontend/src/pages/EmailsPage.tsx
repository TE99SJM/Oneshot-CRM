import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DateRangePicker, Range, defaultRange } from "../components/DateRange";
import { Badge, Drawer, Empty } from "../components/ui";
import { dateTime } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { EmailDetail, EmailPage, EmailRow } from "../types";

const PAGE = 50;
const kb = (n: number) => (n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1000))} KB`);
const who = (e: EmailRow) => (e.direction === "out" ? `To: ${e.to_addrs.split(",")[0].replace(/<.*>/, "").trim() || e.to_addrs}` : e.from_name || e.from_email);

export default function EmailsPage() {
  const [params, setParams] = useSearchParams();
  const contactParam = params.get("contact");
  const [data, setData] = useState<EmailPage | null>(null);
  const [q, setQ] = useState("");
  const [direction, setDirection] = useState("");
  const [show, setShow] = useState(contactParam ? "all" : "contacts");
  const [range, setRange] = useState<Range>(() => defaultRange(contactParam ? "all" : "30"));
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    const p: Record<string, string> = { limit: String(PAGE), offset: String(offset) };
    if (q) p.q = q;
    if (direction) p.direction = direction;
    if (show === "contacts") p.linked = "true";
    if (show === "nobulk") p.include_bulk = "false";
    if (contactParam) p.contact_id = contactParam;
    if (range.from) p.date_from = range.from;
    if (range.to) p.date_to = range.to;
    api.get<EmailPage>(`/emails?${new URLSearchParams(p)}`).then(setData).catch(toastError);
  }, [q, direction, show, range, offset, contactParam]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);
  useEffect(() => setOffset(0), [q, direction, show, range, contactParam]);

  const filtered = !!(q || direction || show !== "all" || range.from || range.to || contactParam);
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Emails</h1><p className="muted">Mail from your Gmail, linked to your contacts. Read-only: nothing is sent or changed in Gmail.</p></div>
      </div>
      {contactParam && data && (
        <div className="row filter-chip">
          Showing emails with <strong>{data.items[0]?.contact_name ?? "this contact"}</strong>
          <button className="btn btn-sm" onClick={() => { params.delete("contact"); setParams(params); setShow("contacts"); setRange(defaultRange()); }}>Show all emails</button>
        </div>
      )}
      <div className="toolbar">
        <input className="search" placeholder="Search subject, person, text…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={show} onChange={(e) => setShow(e.target.value)} aria-label="Which emails" data-testid="email-show">
          <option value="contacts">With my contacts</option>
          <option value="nobulk">All except newsletters</option>
          <option value="all">Everything synced</option>
        </select>
        <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Direction">
          <option value="">Received and sent</option><option value="in">Received</option><option value="out">Sent</option>
        </select>
        <DateRangePicker value={range} onChange={setRange} testId="email-range" />
      </div>

      {!data ? <p className="muted">Loading…</p> : data.items.length === 0 ? (
        filtered ? (
          <Empty title="No emails here">Try “Everything synced” or a wider date range. Haven't connected Gmail yet? Do it on the <Link to="/integrations">Integrations</Link> page (takes a Google app password and about 2 minutes).</Empty>
        ) : (
          <Empty title="No emails yet">Connect Gmail on the <Link to="/integrations">Integrations</Link> page. It takes a Google app password and about 2 minutes.</Empty>
        )
      ) : (
        <>
          <div className="card table-wrap">
            <table className="table emails">
              <thead><tr><th>Date</th><th>From / to</th><th>Subject</th><th>Contact</th></tr></thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id} className={`clickable${e.unread ? " unread" : ""}`} onClick={() => setOpen(e.id)}>
                    <td className="nowrap">{dateTime(e.sent_at)}</td>
                    <td>
                      <div className="row-tight">{e.direction === "out" ? <Badge tone="blue">Sent</Badge> : <Badge>In</Badge>}<span className="ellipsis">{who(e)}</span></div>
                      <div className="muted small ellipsis">{e.direction === "out" ? "" : e.from_email}</div>
                    </td>
                    <td className="email-subj">
                      <div className="ellipsis"><strong>{e.subject}</strong>{e.attachment_count > 0 && <span className="muted small"> · {e.attachment_count} attachment{e.attachment_count > 1 ? "s" : ""}</span>}</div>
                      <div className="muted small ellipsis">{e.snippet}</div>
                    </td>
                    <td>{e.contact_name ?? <span className="muted small">{e.bulk ? "newsletter" : "—"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row pager">
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Newer</button>
            <span className="muted small">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
            <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Older →</button>
          </div>
        </>
      )}
      {open && <EmailDrawer id={open} onOpen={setOpen} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}

/** Email HTML is shown in a locked-down frame: no scripts, and remote images (tracking pixels) blocked until you allow them. */
function HtmlBody({ html, images }: { html: string; images: boolean }) {
  const doc = useMemo(() => {
    const csp = `default-src 'none'; style-src 'unsafe-inline'; img-src data: cid:${images ? " https: http:" : ""}; font-src data:`;
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">
<style>body{font-family:system-ui,sans-serif;font-size:14px;line-height:1.45;margin:0;padding:4px;color:#111;word-wrap:break-word}img{max-width:100%;height:auto}table{max-width:100%}</style></head><body>${html}</body></html>`;
  }, [html, images]);
  const [h, setH] = useState(320);
  return (
    <iframe title="Email" className="email-frame" sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin" srcDoc={doc} style={{ height: h }}
      onLoad={(e) => { try { const b = (e.target as HTMLIFrameElement).contentDocument?.body; if (b) setH(Math.min(Math.max(b.scrollHeight + 16, 120), 4000)); } catch { /* ignore */ } }} />
  );
}

function EmailDrawer({ id, onOpen, onClose, onChanged }: { id: number; onOpen: (id: number) => void; onClose: () => void; onChanged: () => void }) {
  const [e, setE] = useState<EmailDetail | null>(null);
  const [images, setImages] = useState(false);
  const [plain, setPlain] = useState(false);
  const [linking, setLinking] = useState(false);
  const { contacts, loadContacts } = useCrm();
  useEffect(() => { setE(null); setImages(false); api.get<EmailDetail>(`/emails/${id}`).then(setE).catch(toastError); }, [id]);
  useEffect(() => { if (linking && contacts.length === 0) loadContacts().catch(toastError); }, [linking, contacts.length, loadContacts]);

  const link = async (contactId: number | null) => {
    try { setE(await api.patch<EmailDetail>(`/emails/${id}`, { contact_id: contactId })); setLinking(false); onChanged(); }
    catch (err) { toastError(err); }
  };

  return (
    <Drawer title={e ? e.subject : "Email"} onClose={onClose}>
      {!e ? <p className="muted">Loading…</p> : (
        <div className="email-detail">
          <dl className="details">
            <dt>From</dt><dd>{e.from_name ? `${e.from_name} <${e.from_email}>` : e.from_email}</dd>
            <dt>To</dt><dd>{e.to_addrs || "—"}</dd>
            {e.cc_addrs && <><dt>Cc</dt><dd>{e.cc_addrs}</dd></>}
            <dt>Date</dt><dd>{dateTime(e.sent_at)}</dd>
            {e.labels && <><dt>Labels</dt><dd className="small">{e.labels.replace(/\\/g, "")}</dd></>}
            <dt>Contact</dt>
            <dd>
              {e.contact_id ? <><Link to={`/contacts?open=${e.contact_id}`}>{e.contact_name}</Link> <button className="link-btn small" onClick={() => setLinking(true)}>change</button></>
                : <button className="link-btn" onClick={() => setLinking(true)}>Link to a contact</button>}
              {linking && (
                <div className="row" style={{ marginTop: 6 }}>
                  <select defaultValue="" onChange={(ev) => ev.target.value && link(Number(ev.target.value))} data-testid="link-contact">
                    <option value="">Pick a contact…</option>
                    {contacts.map((c) => <option key={c.id} value={c.id}>{`${c.first_name} ${c.last_name}`.trim()}{c.email ? ` (${c.email})` : ""}</option>)}
                  </select>
                  {e.contact_id && <button className="btn btn-sm" onClick={() => link(null)}>Unlink</button>}
                  <button className="btn btn-sm" onClick={() => setLinking(false)}>Cancel</button>
                </div>
              )}
            </dd>
          </dl>
          <div className="row">
            <a className="btn btn-sm" href={e.gmail_url} target="_blank" rel="noreferrer">Open in Gmail ↗</a>
            {e.body_html && <button className="btn btn-sm" onClick={() => setPlain(!plain)}>{plain ? "Formatted view" : "Plain text"}</button>}
            {e.body_html && !plain && !images && <button className="btn btn-sm" onClick={() => setImages(true)}>Load images</button>}
          </div>

          {e.attachments.length > 0 && (
            <div className="attachments">
              {e.attachments.map((a, i) => <span key={i} className="attachment">📎 {a.name} <span className="muted small">{kb(a.size)}</span></span>)}
              <div className="muted small">Attachments stay in Gmail. Use “Open in Gmail” to download them.</div>
            </div>
          )}

          <div className="email-body">
            {e.body_html && !plain ? <HtmlBody html={e.body_html} images={images} /> : <pre className="email-text">{e.body_text || "(no text)"}</pre>}
          </div>

          {e.thread.length > 1 && (
            <>
              <h3>Conversation ({e.thread.length})</h3>
              <ul className="list thread">
                {e.thread.map((t) => (
                  <li key={t.id} className={t.id === e.id ? "current" : "clickable"} onClick={() => t.id !== e.id && onOpen(t.id)}>
                    <div className="grow">
                      <div className="row-tight">{t.direction === "out" ? <Badge tone="blue">Sent</Badge> : <Badge>In</Badge>}<strong>{t.from_name || t.from_email}</strong></div>
                      <div className="muted small ellipsis">{t.snippet}</div>
                    </div>
                    <span className="muted small nowrap">{dateTime(t.sent_at)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Drawer>
  );
}
