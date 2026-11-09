import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Empty, Field, Modal, statusTone } from "../components/ui";
import { dateTime, fromLocalInput, num, parseUtc, toLocalInput } from "../format";
import { channelName, useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { Post, PostStatus } from "../types";

const STATUSES: PostStatus[] = ["idea", "draft", "scheduled", "published"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const postDate = (p: Post) => (p.scheduled_at ?? p.published_at ? parseUtc((p.scheduled_at ?? p.published_at)!) : null);
const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export default function ContentPage() {
  const { posts, loadPosts, channels } = useCrm();
  const [view, setView] = useState<"calendar" | "list">("calendar");
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [channelFilter, setChannelFilter] = useState<number | "">("");
  const [statusFilter, setStatusFilter] = useState<PostStatus | "">("");
  const [editing, setEditing] = useState<Partial<Post> | null>(null);

  useEffect(() => { loadPosts().catch(toastError); }, [loadPosts]);

  const filtered = useMemo(() => posts.filter((p) =>
    (channelFilter === "" || p.channel_id === channelFilter) && (statusFilter === "" || p.status === statusFilter)), [posts, channelFilter, statusFilter]);

  const days = useMemo(() => {
    const start = new Date(month); start.setDate(1 - start.getDay());
    return Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  }, [month]);
  const unscheduled = filtered.filter((p) => !postDate(p));

  const newPostOn = (d?: Date) => {
    const at = d ? new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12) : null;
    setEditing({ title: "", status: at ? "scheduled" : "idea", channel_id: channelFilter || null,
                 scheduled_at: at ? at.toISOString().slice(0, 19) : null });
  };

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Content</h1><p className="muted">Plan, schedule and track social posts across channels.</p></div>
        <div className="row">
          <div className="segmented">
            <button className={view === "calendar" ? "active" : ""} onClick={() => setView("calendar")}>Calendar</button>
            <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>List</button>
          </div>
          <Link className="btn" to="/compose">Post to platforms</Link>
          <button className="btn btn-primary" onClick={() => newPostOn()}>+ Plan a post</button>
        </div>
      </header>

      <div className="toolbar">
        <select value={channelFilter} onChange={(e) => setChannelFilter(e.target.value ? Number(e.target.value) : "")}>
          <option value="">All channels</option>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as PostStatus | "")}>
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {view === "calendar" && (
          <div className="row month-nav" style={{ marginLeft: "auto" }}>
            <button className="btn btn-sm" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>←</button>
            <strong style={{ minWidth: 140, textAlign: "center" }}>{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</strong>
            <button className="btn btn-sm" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>→</button>
          </div>
        )}
      </div>

      {view === "calendar" ? (
        <div className="cal-layout">
          <div className="card calendar">
            {WEEKDAYS.map((w) => <div key={w} className="cal-head">{w}</div>)}
            {days.map((d) => {
              const items = filtered.filter((p) => { const pd = postDate(p); return pd && sameDay(pd, d); });
              return (
                <div key={d.toISOString()} className={`cal-day ${d.getMonth() !== month.getMonth() ? "out" : ""} ${sameDay(d, new Date()) ? "today" : ""}`}
                     onDoubleClick={() => newPostOn(d)}>
                  <div className="cal-num">{d.getDate()}</div>
                  {items.map((p) => (
                    <button key={p.id} className={`cal-item status-${p.status}`} onClick={() => setEditing(p)} title={`${channelName(channels, p.channel_id)} · ${p.title}`}>
                      {p.title}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
          <aside className="card">
            <h3>Idea bank</h3>
            <p className="muted small">Unscheduled ideas. Double-click a calendar day to schedule a new post.</p>
            {unscheduled.length === 0 ? <Empty title="No ideas parked" /> : (
              <ul className="list">{unscheduled.map((p) => (
                <li key={p.id} className="clickable" onClick={() => setEditing(p)}>
                  <div><strong>{p.title}</strong><div className="muted small">{channelName(channels, p.channel_id)}</div></div>
                  <Badge tone={statusTone[p.status]}>{p.status}</Badge>
                </li>))}
              </ul>
            )}
          </aside>
        </div>
      ) : (
        <div className="card table-wrap">
          {filtered.length === 0 ? <Empty title="No posts yet" /> : (
            <table className="table">
              <thead><tr><th>Title</th><th>Channel</th><th>Status</th><th>When</th><th className="num">Views</th><th className="num">Engagement</th><th className="num">Clicks</th></tr></thead>
              <tbody>{filtered.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => setEditing(p)}>
                  <td><strong>{p.url ? <a href={p.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{p.title} ↗</a> : p.title}</strong>{p.external_source && <> <Badge tone="blue">{`synced · ${p.external_source}`}</Badge></>}</td>
                  <td>{channelName(channels, p.channel_id)}</td>
                  <td><Badge tone={statusTone[p.status]}>{p.status}</Badge></td>
                  <td>{dateTime(p.published_at ?? p.scheduled_at)}</td>
                  <td className="num mono">{num(p.views)}</td>
                  <td className="num mono">{num(p.likes + p.comments + p.shares)}</td>
                  <td className="num mono">{num(p.clicks)}</td>
                </tr>))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {editing && <PostForm initial={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function PostForm({ initial, onClose }: { initial: Partial<Post>; onClose: () => void }) {
  const { channels, savePost, deletePost } = useCrm();
  const [form, setForm] = useState<Partial<Post>>(initial);
  const set = (k: keyof Post, v: unknown) => setForm((f) => ({ ...f, [k]: v }));
  const metric = (k: "views" | "likes" | "comments" | "shares" | "clicks") => (
    <Field label={k[0].toUpperCase() + k.slice(1)}><input type="number" min={0} value={form[k] ?? 0} onChange={(e) => set(k, Number(e.target.value))} /></Field>
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    const { id, created_at, ...data } = form as Post;
    void created_at;
    try { await savePost(data, id); onClose(); } catch (err) { toastError(err); }
  }
  async function remove() { if (form.id && confirm("Delete this post?")) { await deletePost(form.id).catch(toastError); onClose(); } }

  return (
    <Modal wide title={form.id ? "Edit post" : "New post"} onClose={onClose}
           footer={<>{form.id && <button type="button" className="btn btn-danger" onClick={remove}>Delete</button>}<span className="grow" />
             <button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="post-form">Save</button></>}>
      <form id="post-form" className="form-grid" onSubmit={submit}>
        <div className="span-2"><Field label="Title / hook"><input required autoFocus value={form.title ?? ""} onChange={(e) => set("title", e.target.value)} /></Field></div>
        <Field label="Channel">
          <select value={form.channel_id ?? ""} onChange={(e) => set("channel_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Status">
          <select value={form.status} onChange={(e) => set("status", e.target.value)}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        </Field>
        <Field label="Scheduled for"><input type="datetime-local" value={toLocalInput(form.scheduled_at)} onChange={(e) => set("scheduled_at", fromLocalInput(e.target.value))} /></Field>
        <Field label="Published URL"><input value={form.url ?? ""} onChange={(e) => set("url", e.target.value)} placeholder="https://" /></Field>
        <div className="span-2"><Field label="Caption / script"><textarea rows={5} value={form.body ?? ""} onChange={(e) => set("body", e.target.value)} /></Field></div>
        <div className="span-2 metrics">{metric("views")}{metric("likes")}{metric("comments")}{metric("shares")}{metric("clicks")}</div>
      </form>
    </Modal>
  );
}
