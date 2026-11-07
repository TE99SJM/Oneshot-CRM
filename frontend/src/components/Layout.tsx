import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../store/authStore";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/orders", label: "Orders" },
  { to: "/emails", label: "Emails" },
  { to: "/messages", label: "Messages" },
  { to: "/contacts", label: "Contacts" },
  { to: "/compose", label: "Compose" },
  { to: "/content", label: "Content" },
  { to: "/channels", label: "Channels" },
  { to: "/integrations", label: "Integrations" },
  { to: "/tasks", label: "Tasks" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  const { user, appName, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    const get = () => api.get<{ unread_total: number }>("/messages?limit=1").then((r) => setUnread(r.unread_total)).catch(() => undefined);
    get(); const t = setInterval(get, 60000); return () => clearInterval(t);
  }, []);
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
              {n.label}
              {n.to === "/messages" && unread > 0 && <span className="pill-count" style={{ marginLeft: 6 }}>{unread}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="muted small">{user?.name || user?.email}</div>
          <button className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
