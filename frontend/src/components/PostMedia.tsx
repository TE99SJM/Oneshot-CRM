import { Dispatch, MutableRefObject, SetStateAction, useEffect, useRef, useState } from "react";
import { api, uploadWithProgress } from "../api/client";
import type { MediaItem } from "../types";

interface Pending { key: number; file: File; progress: number; error?: string }
const ACCEPT = "image/*,video/*,.mp4,.mov,.m4v,.webm,.avi,.mkv";

/** Uploads are temporary until the parent saves their IDs with the calendar plan. */
export default function PostMedia({ media, setMedia, committed, onBusyChange, disabled }: {
  media: MediaItem[]; setMedia: Dispatch<SetStateAction<MediaItem[]>>;
  committed: MutableRefObject<Set<number>>; onBusyChange: (busy: boolean) => void; disabled: boolean;
}) {
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const sequence = useRef(0);
  const removed = useRef(new Set<number>());
  const uploaded = useRef(new Set<number>());
  const discard = (id: number) => { void api.del(`/publish/media/${id}`).catch(() => undefined); };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Saved attachments survive closing/reopening the form; canceled new uploads do not.
      uploaded.current.forEach((id) => { if (!committed.current.has(id)) discard(id); });
    };
  }, [committed]);
  useEffect(() => { onBusyChange(pending.length > 0); }, [pending, onBusyChange]);

  const add = (files: FileList | File[]) => {
    if (disabled) return;
    const chosen = Array.from(files);
    if (!chosen.length) return;
    if (media.length + pending.length + chosen.length > 20) {
      setError("Attach up to 20 photos or videos to one plan.");
      return;
    }
    setError("");
    const entries = chosen.map((file) => ({ key: ++sequence.current, file, progress: 0 }));
    setPending((items) => [...items, ...entries]);
    onBusyChange(true);
    void (async () => {
      // Stream one file at a time so large videos do not compete for upload bandwidth.
      for (const entry of entries) {
        if (!mounted.current || removed.current.has(entry.key)) continue;
        const form = new FormData();
        form.append("files", entry.file);
        try {
          const [saved] = await uploadWithProgress<MediaItem[]>("/publish/media", form, (progress) => {
            if (mounted.current) setPending((items) => items.map((p) => p.key === entry.key ? { ...p, progress } : p));
          });
          if (!saved) throw new Error("Upload did not return a file. Please try again.");
          if (!mounted.current || removed.current.has(entry.key)) { discard(saved.id); continue; }
          uploaded.current.add(saved.id);
          setMedia((items) => [...items, saved]);
          setPending((items) => items.filter((p) => p.key !== entry.key));
        } catch (e) {
          if (mounted.current) setPending((items) => items.map((p) => p.key === entry.key
            ? { ...p, error: e instanceof Error ? e.message : String(e) } : p));
        }
      }
    })();
  };

  return <section aria-label="Post media" className="plan-media">
    <strong>Photos / videos</strong>
    <p className="muted small">Attach media to this plan. Saving keeps your files with the draft; it does not publish them.</p>
    <div className="dropzone" role="button" tabIndex={disabled ? -1 : 0} aria-disabled={disabled}
      onClick={() => { if (!disabled) input.current?.click(); }}
      onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); if (!disabled) input.current?.click(); } }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); add(e.dataTransfer.files); }}>
      <strong>Add photos or videos</strong>
      <span className="muted small">Choose files or drag them here. MP4, MOV, JPG and PNG are supported.</span>
      <input ref={input} type="file" multiple accept={ACCEPT} hidden disabled={disabled} aria-label="Upload post media"
        onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
    </div>
    {error && <p className="error-box small" role="alert">{error}</p>}
    <div className="media-grid">
      {media.map((m) => <div key={m.id} className="media-tile">
        {m.kind === "video" ? <video src={m.url} controls preload="metadata" playsInline aria-label={m.filename} />
          : <img src={m.url} alt={m.filename} loading="lazy" />}
        <div className="media-meta small"><span className="ellipsis" title={m.filename}>{m.filename}</span>
          <span className="muted">{(m.size / 1048576).toFixed(1)} MB</span></div>
        <button type="button" className="icon-btn media-remove" disabled={disabled} aria-label={`Remove ${m.filename}`}
          onClick={() => {
            setMedia((items) => items.filter((item) => item.id !== m.id));
            // Existing attachments are only detached when Save succeeds, so Cancel is safe.
            if (uploaded.current.has(m.id) && !committed.current.has(m.id)) { discard(m.id); uploaded.current.delete(m.id); }
          }}>×</button>
      </div>)}
      {pending.map((p) => <div key={`pending-${p.key}`} className="media-tile">
        <span className="small ellipsis" title={p.file.name}>{p.file.name}</span>
        {p.error ? <p className="error-box small" role="alert">{p.error}</p> : <>
          <span className="small" role="status">{p.progress === 100 ? "Saving upload…" : `Uploading ${p.progress}%`}</span>
          <progress value={p.progress} max={100} aria-label={`Uploading ${p.file.name}`} />
        </>}
        <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => {
          removed.current.add(p.key); setPending((items) => items.filter((item) => item.key !== p.key));
        }}>Remove {p.error ? "failed file" : "upload"}</button>
      </div>)}
    </div>
  </section>;
}
