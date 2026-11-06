import { create } from "zustand";
import { api, setUnauthorizedHandler, tokenStore } from "../api/client";
import type { User } from "../types";

type Phase = "loading" | "setup" | "login" | "authed";

interface AuthState {
  phase: Phase;
  user: User | null;
  appName: string;
  init: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  setup: (email: string, name: string, password: string) => Promise<void>;
  logout: () => void;
}

interface TokenResponse { access_token: string; user: User }

export const useAuth = create<AuthState>((set, get) => ({
  phase: "loading",
  user: null,
  appName: "FunnelHub CRM",

  async init() {
    const status = await api.get<{ needs_setup: boolean; app_name: string }>("/auth/status");
    set({ appName: status.app_name });
    if (status.needs_setup) { tokenStore.clear(); set({ phase: "setup" }); return; }
    if (!tokenStore.get()) { set({ phase: "login" }); return; }
    try {
      set({ user: await api.get<User>("/auth/me"), phase: "authed" });
    } catch {
      get().logout();
    }
  },

  async login(email, password) {
    const r = await api.post<TokenResponse>("/auth/login", { email, password });
    tokenStore.set(r.access_token);
    set({ user: r.user, phase: "authed" });
  },

  async setup(email, name, password) {
    const r = await api.post<TokenResponse>("/auth/setup", { email, name, password });
    tokenStore.set(r.access_token);
    set({ user: r.user, phase: "authed" });
  },

  logout() {
    tokenStore.clear();
    set({ user: null, phase: "login" });
  },
}));

setUnauthorizedHandler(() => {
  if (useAuth.getState().phase === "authed") useAuth.getState().logout();
});
