import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../store/authStore";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/orders", label: "Orders" },
  { to: "/contacts", label: "Contacts" },
  { to: "/content", label: "Content" },
  { to: "/channels", label: "Channels" },
  { to: "/integrations", label: "Integrations" },
  { to: "/tasks", label: "Tasks" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  const { user, appName, logout } = useAuth();
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
