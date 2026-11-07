import { ReactNode, useEffect } from "react";
import { useToasts } from "../store/toastStore";

export function Modal({ title, onClose, children, footer, wide }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay overlay-right" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer">
        <header className="modal-head"><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Stat({ label, value, sub, period, onClick, testId }: {
  label: string; value: ReactNode; sub?: ReactNode; period?: string; onClick?: () => void; testId?: string;
}) {
  const body = (
    <>
      <div className="stat-label">{label}{period && <span className="stat-period">{period}</span>}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
      {onClick && <div className="stat-open" aria-hidden="true">View chart ↗</div>}
    </>
  );
  return onClick
    ? <button type="button" className="card stat stat-button" onClick={onClick} data-testid={testId} title={`Open ${label} chart`}>{body}</button>
    : <div className="card stat" data-testid={testId}>{body}</div>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><strong>{title}</strong>{children && <div>{children}</div>}</div>;
}

/** Horizontal bar list, used for simple charts without a chart library. */
export function BarList({ rows, format = String }: {
  rows: { label: string; value: number; tone?: string }[]; format?: (n: number) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <Empty title="No data yet" />;
  return (
    <ul className="barlist">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="barlist-top"><span>{r.label}</span><span className="mono">{format(r.value)}</span></div>
          <div className="bar"><div className={`bar-fill ${r.tone ?? ""}`} style={{ width: `${(r.value / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

export function Toasts() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <button key={t.id} className={`toast toast-${t.tone}`} onClick={() => dismiss(t.id)}>{t.message}</button>
      ))}
    </div>
  );
}

export const statusTone: Record<string, string> = {
  lead: "blue", prospect: "amber", customer: "green", inactive: "neutral",
  open: "blue", won: "green", lost: "red",
  idea: "neutral", draft: "amber", scheduled: "blue", published: "green",
};
