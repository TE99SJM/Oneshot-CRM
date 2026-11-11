import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Toasts } from "./components/ui";
import ChannelsPage from "./pages/ChannelsPage";
import ContactsPage from "./pages/ContactsPage";
import ComposePage from "./pages/ComposePage";
import ContentPage from "./pages/ContentPage";
import DashboardPage from "./pages/DashboardPage";
import IntegrationsPage from "./pages/IntegrationsPage";
import OrdersPage from "./pages/OrdersPage";
import EmailsPage from "./pages/EmailsPage";
import MessagesPage from "./pages/MessagesPage";
import LoginPage from "./pages/LoginPage";
import PipelinePage from "./pages/PipelinePage";
import SettingsPage from "./pages/SettingsPage";
import TasksPage from "./pages/TasksPage";
import { useAuth } from "./store/authStore";
import { useCrm } from "./store/crmStore";
import { toastError } from "./store/toastStore";
import { useAutoSync } from "./hooks/useAutoSync";

export default function App() {
  const { phase, init } = useAuth();
  const loadReference = useCrm((s) => s.loadReference);
  const [bootError, setBootError] = useState("");
  useAutoSync(phase === "authed");

  useEffect(() => { init().catch((e) => setBootError(e instanceof Error ? e.message : String(e))); }, [init]);
  useEffect(() => { if (phase === "authed") loadReference().catch(toastError); }, [phase, loadReference]);

  if (bootError) {
    return (
      <div className="center-screen">
        <div className="card auth-card">
          <h1>Can't reach the API</h1>
          <p className="muted">Make sure the backend is running on port 8000, then reload.</p>
          <pre className="error-box">{bootError}</pre>
        </div>
      </div>
    );
  }
  if (phase === "loading") return <div className="center-screen muted">Loading…</div>;

  return (
    <>
      {phase !== "authed" ? <LoginPage /> : (
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="pipeline" element={<PipelinePage />} />
            <Route path="contacts" element={<ContactsPage />} />
            <Route path="content" element={<ContentPage />} />
            <Route path="compose" element={<ComposePage />} />
            <Route path="channels" element={<ChannelsPage />} />
            <Route path="integrations" element={<IntegrationsPage />} />
            <Route path="orders" element={<OrdersPage />} />
            <Route path="emails" element={<EmailsPage />} />
            <Route path="messages" element={<MessagesPage />} />
            <Route path="tasks" element={<TasksPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      )}
      <Toasts />
    </>
  );
}
