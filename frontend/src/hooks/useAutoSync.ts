import { useEffect } from "react";
import { create } from "zustand";
import { api } from "../api/client";
import { useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { Integration } from "../types";

const useSyncState = create<{ revision: number }>(() => ({ revision: 0 }));
export const useSyncRevision = () => useSyncState((s) => s.revision);

/** Start one refresh after sign-in and watch saved sync results without remounting any forms. */
export function useAutoSync(authenticated: boolean) {
  useEffect(() => {
    if (!authenticated) return;
    let active = true;
    let checking = false;
    let launchPending = true;
    let launchErrorShown = false;
    let signature = "";

    const check = async () => {
      if (!active || checking || document.hidden || navigator.onLine === false) return;
      checking = true;
      try {
        if (launchPending) {
          await api.post("/integrations/browser-open");
          launchPending = false;
        }
        if (!active) return;
        const items = await api.get<Integration[]>("/integrations");
        if (!active) return;
        const next = JSON.stringify(items.map((i) => [i.id, i.last_sync_at, i.last_status, i.last_error,
          i.enabled, i.sync_interval_minutes, i.sync_on_open]));
        if (next !== signature) {
          await useCrm.getState().loadReference();
          if (!active) return;
          signature = next;
          useSyncState.setState((s) => ({ revision: s.revision + 1 }));
        }
      } catch (error) {
        // A launch request that failed is retried on the next check or network reconnect.
        // Background polling failures do not repeatedly interrupt the user with toasts.
        if (active && launchPending && !launchErrorShown && navigator.onLine) {
          toastError(error);
          launchErrorShown = true;
        }
      } finally { checking = false; }
    };

    void check();
    const timer = window.setInterval(() => { void check(); }, 15000);
    const resume = () => { void check(); };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
    };
  }, [authenticated]);
}
