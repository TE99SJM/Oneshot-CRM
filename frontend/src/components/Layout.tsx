import { ReactNode, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../store/authStore";

/** Simple line icons (24×24, stroke = currentColor) so the phone tab bar reads like a native app. */
const I = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const ICONS: Record<string, ReactNode> = {
  "/": I(<><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /><path d="M10 20v-6h4v6" /></>),
  "/pipeline": I(<><rect x="3" y="4" width="5" height="16" rx="1" /><rect x="10" y="4" width="5" height="11" rx="1" /><rect x="17" y="4" width="4" height="7" rx="1" /></>),
  "/orders": I(<><path d="M6 2l-2 4v14a2 2 0 002 2h12a2 2 0 002-2V6l-2-4z" /><path d="M4 6h16" /><path d="M16 10a4 4 0 01-8 0" /></>),
  "/emails": I(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>),
  "/messages": I(<path d="M21 12a8 8 0 01-11.6 7.1L3 21l1.9-6.4A8 8 0 1121 12z" />),
  "/contacts": I(<><circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0114 0" /><path d="M17 4a4 4 0 010 8" /><path d="M22 21a7 7 0 00-4-6.3" /></>),
  "/compose": I(<><circle cx="12" cy="12" r="9" /><path d="M12 8v8M8 12h8" /></>),
  "/content": I(<><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M10 8l6 4-6 4z" /></>),
  "/channels": I(<><path d="M4 11a9 9 0 019 9" /><path d="M4 4a16 16 0 0116 16" /><circle cx="5" cy="19" r="1.5" /></>),
  "/integrations": I(<><path d="M9 3v4M15 3v4" /><path d="M6 7h12v4a6 6 0 01-12 0z" /><path d="M12 17v4" /></>),
  "/tasks": I(<><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" /></>),
  "/settings": I(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></>),
  more: I(<><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>),
  chevron: <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>,
};

const NAV = [
  { to: "/", label: "Dashboard", short: "Home", end: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/orders", label: "Orders" },
  { to: "/emails", label: "Emails" },
  { to: "/messages", label: "Messages" },
  { to: "/contacts", label: "Contacts" },
  { to: "/compose", label: "Compose", short: "Post" },
  { to: "/content", label: "Content" },
  { to: "/channels", label: "Channels" },
  { to: "/integrations", label: "Integrations" },
  { to: "/tasks", label: "Tasks" },
  { to: "/settings", label: "Settings" },
];
/** The four pages that get their own button on the phone tab bar; everything else lives under "More". */
const TABS = ["/", "/orders", "/messages", "/compose"];

/** On phones, tables turn into stacked cards; each cell needs its column name to show as a label. */
function useTableLabels() {
  useEffect(() => {
    const label = () => {
      document.querySelectorAll<HTMLTableElement>("table.table").forEach((t) => {
        const heads = Array.from(t.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "");
        t.querySelectorAll("tbody tr").forEach((tr) =>
          Array.from(tr.children).forEach((td, i) => {
            const want = heads[i] ?? "";
            if (td.getAttribute("data-label") !== want) td.setAttribute("data-label", want);
          }));
      });
    };
    label();
    const obs = new MutationObserver(label);
    obs.observe(document.body, { childList: true, subtree: true });
    return () => obs.disconnect();
  }, []);
}

export default function Layout() {
  const { user, appName, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  const [more, setMore] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();
  useTableLabels();
  useEffect(() => {
    const get = () => api.get<{ unread_total: number }>("/messages?limit=1").then((r) => setUnread(r.unread_total)).catch(() => undefined);
    get(); const t = setInterval(get, 60000); return () => clearInterval(t);
  }, []);
  useEffect(() => { setMore(false); window.scrollTo(0, 0); }, [loc.pathname]);
  // iPhone-style: the bar shows the app name until the big page title scrolls away, then the page name.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 56);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  const current = NAV.find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to))) ?? NAV[0];
  const inMore = !TABS.includes(current.to);
  const badge = (to: string) => to === "/messages" && unread > 0 && <span className="pill-count">{unread}</span>;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><path d="M4 6h24l-9 11v8l-6 3V17z" fill="currentColor" /></svg>
          <span>{appName}</span>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              {n.label}{badge(n.to)}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="muted small">{user?.name || user?.email}</div>
          <button className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
        </div>
      </aside>

      {/* phone only: app-style title bar */}
      <header className="appbar" data-testid="appbar">
        <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true"><path d="M4 6h24l-9 11v8l-6 3V17z" fill="currentColor" /></svg>
        <span className="appbar-title">{more ? "More" : scrolled ? current.label : appName}</span>
      </header>

      <main className="main"><Outlet /></main>

      {/* phone only: bottom tab bar */}
      <nav className="tabbar" aria-label="Main" data-testid="tabbar">
        {TABS.map((to) => {
          const n = NAV.find((x) => x.to === to)!;
          return (
            <NavLink key={to} to={to} end={n.end} className={({ isActive }) => `tab ${isActive && !more ? "active" : ""}`}>
              <span className="tab-icon">{ICONS[to]}{badge(to)}</span>
              <span>{n.short ?? n.label}</span>
            </NavLink>
          );
        })}
        <button className={`tab ${inMore || more ? "active" : ""}`} onClick={() => setMore((m) => !m)} data-testid="tab-more" aria-expanded={more}>
          <span className="tab-icon">{ICONS.more}</span>
          <span>More</span>
        </button>
      </nav>

      {more && (
        <div className="more-sheet" role="dialog" aria-label="All pages" data-testid="more-sheet">
          <h2 className="more-title">All pages</h2>
          <div className="more-list">
            {NAV.filter((n) => !TABS.includes(n.to)).map((n) => (
              <button key={n.to} className={`more-row ${current.to === n.to ? "active" : ""}`} onClick={() => nav(n.to)}>
                <span className="more-icon">{ICONS[n.to]}</span>
                <span className="grow">{n.label}</span>
                {ICONS.chevron}
              </button>
            ))}
          </div>
          <div className="more-list">
            <div className="more-row static"><span className="grow">Signed in as <strong>{user?.name || user?.email}</strong></span></div>
            <button className="more-row danger" onClick={logout}><span className="grow">Sign out</span></button>
          </div>
        </div>
      )}
    </div>
  );
}
