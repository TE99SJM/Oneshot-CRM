import { DragEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, uploadWithProgress } from "../api/client";
import { Badge, Empty, Field, Modal } from "../components/ui";
import { dateTime, fromLocalInput, toLocalInput } from "../format";
import { useCrm } from "../store/crmStore";
import { toastError, useToasts } from "../store/toastStore";
import type { MediaItem, PublishJob, PublishPlatform, PublishTarget, PublishTargetOption } from "../types";

const PLATFORM_LABEL: Record<PublishPlatform, string> = { facebook: "Facebook", instagram: "Instagram", youtube: "YouTube" };
const TARGET_TONE: Record<PublishTarget["status"], string> = {
  pending: "blue", posting: "amber", processing: "green", posted: "green", failed: "red", canceled: "neutral",
};
const TARGET_LABEL: Record<PublishTarget["status"], string> = {
  pending: "Waiting", posting: "Posting…", processing: "Posted (processing)", posted: "Posted", failed: "Failed", canceled: "Canceled",
};
const JOB_TONE: Record<PublishJob["status"], string> = {
  scheduled: "blue", posting: "amber", done: "green", partial: "amber", failed: "red", canceled: "neutral",
};
const JOB_LABEL: Record<PublishJob["status"], string> = {
  scheduled: "Scheduled", posting: "Posting…", done: "Posted", partial: "Partly posted", failed: "Failed", canceled: "Canceled",
};
const LIMITS: Record<PublishPlatform, number> = { facebook: 63206, instagram: 2200, youtube: 5000 };

interface Pending { key: string; file: File; preview: string; progress: number; media?: MediaItem; error?: string; vertical?: boolean }
interface YtOptions { privacy: string; made_for_kids: boolean; tags: string; notify: boolean }

const size = (n: number) => (n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.ceil(n / 1e3)} KB`);
const isVideo = (f: File) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(f.name);

export default function ComposePage() {
  const loadPosts = useCrm((s) => s.loadPosts);
  const push = useToasts((s) => s.push);
  const [targets, setTargets] = useState<PublishTargetOption[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [link, setLink] = useState("");
  const [files, setFiles] = useState<Pending[]>([]);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [at, setAt] = useState("");
  const [yt, setYt] = useState<YtOptions>({ privacy: "public", made_for_kids: false, tags: "", notify: true });
  const [fbReel, setFbReel] = useState(false);
  const [igFeed, setIgFeed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [rescheduling, setRescheduling] = useState<PublishJob | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadJobs = useCallback(async () => setJobs(await api.get<PublishJob[]>("/publish", { limit: 50 })), []);
  useEffect(() => {
    api.get<PublishTargetOption[]>("/publish/targets").then((t) => {
      setTargets(t);
      setSelected(t.filter((x) => x.ready && x.enabled).map((x) => x.integration_id));
    }).catch(toastError);
    loadJobs().catch(toastError);
  }, [loadJobs]);
  const anyPosting = jobs.some((j) => j.status === "posting");
  useEffect(() => {
    if (!anyPosting) return;
    const t = setInterval(() => loadJobs().catch(() => undefined), 4000);
    return () => clearInterval(t);
  }, [anyPosting, loadJobs]);
  useEffect(() => () => files.forEach((f) => URL.revokeObjectURL(f.preview)), []); // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = useMemo(() => (targets ?? []).filter((t) => selected.includes(t.integration_id)), [targets, selected]);
  const platforms = new Set(chosen.map((t) => t.platform));
  const images = files.filter((f) => !isVideo(f.file));
  const videos = files.filter((f) => isVideo(f.file));
  const uploading = files.some((f) => !f.media && !f.error);
  const caption = link && !text.includes(link) ? `${text}\n\n${link}`.trim() : text;
  const needsTitle = platforms.has("youtube") || (platforms.has("facebook") && videos.length > 0);

  const problems: string[] = [];
  if (!chosen.length) problems.push("Pick at least one place to post.");
  if (platforms.has("facebook") && !text.trim() && !link.trim() && !files.length) problems.push("Facebook needs text, a link, or media.");
  if (platforms.has("facebook") && videos.length && images.length) problems.push("Facebook can't mix photos and a video in one post.");
  if (videos.length > 1) problems.push("Attach only one video per post.");
  if (platforms.has("instagram") && !files.length) problems.push("Instagram needs a photo or a video.");
  if (platforms.has("instagram") && videos.length && images.length) problems.push("Instagram: one video on its own, or photos only.");
  if (platforms.has("instagram") && caption.length > 2200) problems.push("Instagram captions max out at 2,200 characters.");
  if (platforms.has("youtube") && (videos.length !== 1 || images.length)) problems.push("YouTube needs exactly one video and no photos.");
  if (platforms.has("youtube") && !(title.trim() || text.trim())) problems.push("Give the YouTube video a title.");
  if (platforms.has("youtube") && title.length > 100) problems.push("YouTube titles max out at 100 characters.");
  if (when === "later" && !at) problems.push("Pick a date and time, or choose Post now.");
  if (files.some((f) => f.error)) problems.push("Remove the files that failed to upload.");

  const addFiles = (list: FileList | File[]) => {
    const added: Pending[] = Array.from(list).map((file) => ({ key: `${file.name}-${file.size}-${Math.random()}`, file, preview: URL.createObjectURL(file), progress: 0 }));
    setFiles((cur) => [...cur, ...added]);
    added.forEach((p) => {
      const form = new FormData();
      form.append("files", p.file);
      uploadWithProgress<MediaItem[]>("/publish/media", form, (pct) =>
        setFiles((cur) => cur.map((f) => (f.key === p.key ? { ...f, progress: pct } : f))))
        .then(([media]) => setFiles((cur) => cur.map((f) => (f.key === p.key ? { ...f, media, progress: 100 } : f))))
        .catch((e) => setFiles((cur) => cur.map((f) => (f.key === p.key ? { ...f, error: e instanceof Error ? e.message : String(e) } : f))));
    });
  };
  const removeFile = (p: Pending) => {
    URL.revokeObjectURL(p.preview);
    setFiles((cur) => cur.filter((f) => f.key !== p.key));
    if (p.media) api.del(`/publish/media/${p.media.id}`).catch(() => undefined);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); };
  const markVertical = (key: string, w: number, h: number) =>
    setFiles((cur) => cur.map((f) => (f.key === key ? { ...f, vertical: h > w } : f)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (problems.length || uploading) return;
    setBusy(true);
    try {
      const body = {
        title: title.trim(), text, link: link.trim(), media_ids: files.map((f) => f.media!.id),
        scheduled_at: when === "later" ? fromLocalInput(at) : null,
        targets: chosen.map((t) => ({
          integration_id: t.integration_id,
          options: t.platform === "youtube" ? { ...yt }
            : t.platform === "facebook" ? { as_reel: fbReel && videos.length > 0 }
            : { share_to_feed: igFeed },
        })),
      };
      const job = await api.post<PublishJob>("/publish", body);
      push(when === "later" ? `Scheduled for ${dateTime(job.scheduled_at)}.` : "Posting now. Results appear below.", "success");
      files.forEach((f) => URL.revokeObjectURL(f.preview));
      setFiles([]); setText(""); setTitle(""); setLink(""); setAt(""); setWhen("now");
      await loadJobs();
      loadPosts().catch(() => undefined);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };

  const act = async (job: PublishJob, action: "post-now" | "retry" | "cancel" | "delete") => {
    try {
      if (action === "delete") {
        if (!confirm("Remove this from the history? Anything already posted stays on the platforms.")) return;
        await api.del(`/publish/${job.id}`);
      } else {
        if (action === "cancel" && !confirm("Cancel this scheduled post?")) return;
        await api.post(`/publish/${job.id}/${action}`);
      }
      await loadJobs();
      loadPosts().catch(() => undefined);
    } catch (err) { toastError(err); }
  };

  const vertical = videos.some((v) => v.vertical);
  const readyCount = (targets ?? []).filter((t) => t.ready).length;

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Compose</h1><p className="muted">Write once and post to Facebook, Instagram and YouTube, now or on a schedule.</p></div>
      </header>

      {targets && !targets.length && (
        <div className="callout">
          No posting accounts yet. Connect Facebook, Instagram or YouTube in <Link to="/integrations">Integrations</Link> first.
        </div>
      )}

      <form className="compose-grid" onSubmit={submit}>
        <section className="card compose-main">
          <Field label="Post text" hint={[...platforms].map((p) => `${PLATFORM_LABEL[p]} ${caption.length.toLocaleString()}/${LIMITS[p].toLocaleString()}`).join(" · ") || undefined}>
            <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="What do you want to say?" data-testid="compose-text" />
          </Field>
          <Field label="Link (optional)" hint="Facebook shows a link preview. On Instagram links aren't clickable; it's added to the caption.">
            <input type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://..." />
          </Field>
          {needsTitle && (
            <Field label={`Video title ${title.length ? `(${title.length}/100)` : ""}`} hint="Used for YouTube and Facebook videos. Leave blank to use the first line of the text.">
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="My video title" data-testid="compose-title" />
            </Field>
          )}

          <div className={`dropzone ${dragOver ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)} onDrop={onDrop} onClick={() => fileInput.current?.click()} role="button" tabIndex={0}>
            <strong>Add photos or a video</strong>
            <span className="muted small">Drag files here or click to choose. Photos: JPG/PNG. Video: MP4 or MOV.</span>
            <input ref={fileInput} type="file" multiple accept="image/*,video/*" hidden data-testid="compose-files"
              onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
          </div>
          {!!files.length && (
            <div className="media-grid">
              {files.map((f) => (
                <div key={f.key} className="media-tile">
                  {isVideo(f.file)
                    ? <video src={f.preview} muted onLoadedMetadata={(e) => markVertical(f.key, e.currentTarget.videoWidth, e.currentTarget.videoHeight)} />
                    : <img src={f.preview} alt={f.file.name} />}
                  <div className="media-meta small">
                    <span className="ellipsis" title={f.file.name}>{f.file.name}</span>
                    <span className="muted">{size(f.file.size)}</span>
                  </div>
                  {f.error ? <div className="error-box small">{f.error}</div>
                    : !f.media && <div className="bar"><div className="bar-fill" style={{ width: `${f.progress}%` }} /></div>}
                  <button type="button" className="icon-btn media-remove" aria-label={`Remove ${f.file.name}`} onClick={() => removeFile(f)}>×</button>
                </div>
              ))}
            </div>
          )}
        </section>

        <aside className="compose-side">
          <section className="card">
            <h3>Post to</h3>
            {targets === null ? <p className="muted small">Loading…</p> : (
              <div className="target-list">
                {targets.map((t) => (
                  <label key={t.integration_id} className={`target ${t.ready ? "" : "disabled"}`}>
                    <input type="checkbox" disabled={!t.ready} checked={selected.includes(t.integration_id)}
                      onChange={(e) => setSelected((s) => e.target.checked ? [...s, t.integration_id] : s.filter((x) => x !== t.integration_id))} />
                    <span>
                      <span className={`platform-dot p-${t.platform}`} />
                      <strong>{PLATFORM_LABEL[t.platform]}</strong> <span className="muted small">{t.account || t.name}</span>
                      {!t.ready && <span className="small warn-text"><br />{t.note} <Link to="/integrations">Fix ↗</Link></span>}
                    </span>
                  </label>
                ))}
                {!!targets.length && readyCount < targets.length && <p className="muted small">Greyed-out accounts need one more setup step.</p>}
              </div>
            )}
          </section>

          {platforms.has("youtube") && (
            <section className="card">
              <h3>YouTube</h3>
              <Field label="Visibility">
                <select value={yt.privacy} onChange={(e) => setYt({ ...yt, privacy: e.target.value })}>
                  <option value="public">Public</option><option value="unlisted">Unlisted</option><option value="private">Private</option>
                </select>
              </Field>
              <Field label="Made for kids?" hint="YouTube requires an answer. Most hunting, outdoors and shop content is “No”.">
                <select value={yt.made_for_kids ? "yes" : "no"} onChange={(e) => setYt({ ...yt, made_for_kids: e.target.value === "yes" })}>
                  <option value="no">No, it's not made for kids</option><option value="yes">Yes, it's made for kids</option>
                </select>
              </Field>
              <Field label="Tags (optional)" hint="Comma separated."><input value={yt.tags} onChange={(e) => setYt({ ...yt, tags: e.target.value })} placeholder="elk, hunting, minnesota" /></Field>
              <label className="row small"><input type="checkbox" checked={yt.notify} onChange={(e) => setYt({ ...yt, notify: e.target.checked })} /> Notify subscribers</label>
              {vertical && <p className="muted small">Vertical videos under 3 minutes become YouTube Shorts automatically.</p>}
            </section>
          )}
          {platforms.has("facebook") && videos.length > 0 && (
            <section className="card">
              <h3>Facebook</h3>
              <label className="row small"><input type="checkbox" checked={fbReel} onChange={(e) => setFbReel(e.target.checked)} /> Post the video as a Reel</label>
              <p className="muted small">{vertical ? "This video is vertical, so a Reel is a good fit." : "Reels need a vertical (9:16) video, 3–90 seconds."}</p>
            </section>
          )}
          {platforms.has("instagram") && videos.length > 0 && (
            <section className="card">
              <h3>Instagram</h3>
              <p className="muted small">Videos post as a Reel.</p>
              <label className="row small"><input type="checkbox" checked={igFeed} onChange={(e) => setIgFeed(e.target.checked)} /> Also show it in the main feed</label>
            </section>
          )}

          <section className="card">
            <h3>When</h3>
            <div className="segmented">
              <button type="button" className={when === "now" ? "active" : ""} onClick={() => setWhen("now")}>Post now</button>
              <button type="button" className={when === "later" ? "active" : ""} onClick={() => setWhen("later")}>Schedule</button>
            </div>
            {when === "later" && (
              <Field label="Date and time" hint="Your local time. The CRM server must be running at that time.">
                <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} data-testid="compose-at" />
              </Field>
            )}
            {problems.length > 0 && (text || link || files.length > 0 || when === "later") && <ul className="problems small">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
            <button type="submit" className="btn btn-primary btn-block" disabled={busy || uploading || problems.length > 0} data-testid="compose-submit">
              {uploading ? "Uploading files…" : busy ? "Sending…" : when === "later" ? "Schedule post" : `Post to ${chosen.length || ""} ${chosen.length === 1 ? "account" : "accounts"}`}
            </button>
          </section>
        </aside>
      </form>

      <section className="card">
        <div className="row-between"><h2>Posts sent from here</h2><button className="btn btn-sm" onClick={() => loadJobs().catch(toastError)}>Refresh</button></div>
        {!jobs.length ? <Empty title="Nothing posted yet">Posts you send or schedule above show up here with links to each platform.</Empty> : (
          <div className="job-list">
            {jobs.map((j) => (
              <article key={j.id} className="job" data-testid={`job-${j.id}`}>
                <div className="job-head">
                  <Badge tone={JOB_TONE[j.status]}>{JOB_LABEL[j.status]}</Badge>
                  <span className="muted small">
                    {j.status === "scheduled" ? `for ${dateTime(j.scheduled_at)}` : dateTime(j.finished_at ?? j.created_at)}
                  </span>
                  <div className="row job-actions">
                    {j.status === "scheduled" && <>
                      <button className="btn btn-sm" onClick={() => setRescheduling(j)}>Change time</button>
                      <button className="btn btn-sm btn-primary" onClick={() => act(j, "post-now")}>Post now</button>
                      <button className="btn btn-sm" onClick={() => act(j, "cancel")}>Cancel</button>
                    </>}
                    {(j.status === "failed" || j.status === "partial") && !j.media_deleted && j.targets.some((t) => t.status === "failed") &&
                      <button className="btn btn-sm btn-primary" onClick={() => act(j, "retry")}>Retry failed</button>}
                    {j.status !== "posting" && j.status !== "scheduled" && <button className="btn btn-sm btn-ghost" onClick={() => act(j, "delete")}>Remove</button>}
                  </div>
                </div>
                <div className="job-body">
                  {j.media[0] && (j.media[0].kind === "image"
                    ? <img className="job-thumb" src={j.media[0].url} alt="" />
                    : <div className="job-thumb video-thumb">▶</div>)}
                  <div>
                    {j.title && <strong>{j.title}</strong>}
                    <p className="job-text">{j.text || j.link || <span className="muted">(no text)</span>}</p>
                    {j.media.length > 1 && <span className="muted small">{j.media.length} files</span>}
                  </div>
                </div>
                <ul className="job-targets">
                  {j.targets.map((t) => (
                    <li key={t.id}>
                      <span className={`platform-dot p-${t.platform}`} /> <strong>{PLATFORM_LABEL[t.platform]}</strong>
                      <span className="muted small">{t.name}</span>
                      <Badge tone={TARGET_TONE[t.status]}>{TARGET_LABEL[t.status]}</Badge>
                      {t.url && <a href={t.url} target="_blank" rel="noreferrer" className="small">Open ↗</a>}
                      {t.error && <div className={`small ${t.status === "failed" ? "error-box" : "muted"}`}>{t.error}</div>}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        )}
      </section>

      {rescheduling && <Reschedule job={rescheduling} onClose={() => setRescheduling(null)} onSaved={async () => { setRescheduling(null); await loadJobs(); }} />}
    </div>
  );
}

function Reschedule({ job, onClose, onSaved }: { job: PublishJob; onClose: () => void; onSaved: () => void }) {
  const [at, setAt] = useState(toLocalInput(job.scheduled_at));
  const [text, setText] = useState(job.text);
  const [saving, setSaving] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try { await api.patch(`/publish/${job.id}`, { scheduled_at: fromLocalInput(at), text }); onSaved(); }
    catch (err) { toastError(err); } finally { setSaving(false); }
  };
  return (
    <Modal title="Change scheduled post" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Close</button><button className="btn btn-primary" form="resched" disabled={saving || !at}>Save</button></>}>
      <form id="resched" className="form-grid" onSubmit={save}>
        <Field label="Date and time"><input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} required /></Field>
        <Field label="Post text"><textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </form>
    </Modal>
  );
}
