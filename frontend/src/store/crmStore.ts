/**
 * Central CRM state.  Reference data (channels, funnels) is cached app-wide; list views
 * (contacts, deals, posts) are loaded on demand and patched in place after mutations.
 */
import { create } from "zustand";
import { api } from "../api/client";
import type { Channel, Contact, ContactStatus, Deal, Funnel, Post, Stage } from "../types";

export interface ContactFilters { q: string; status: ContactStatus | ""; channel_id: number | ""; tag: string }

interface CrmState {
  channels: Channel[];
  funnels: Funnel[];
  contacts: Contact[];
  contactTotal: number;
  contactFilters: ContactFilters;
  deals: Deal[];
  posts: Post[];
  loading: Record<string, boolean>;

  loadReference: () => Promise<void>;
  loadChannels: () => Promise<void>;
  saveChannel: (data: Partial<Channel>, id?: number) => Promise<Channel>;
  deleteChannel: (id: number) => Promise<void>;

  setContactFilters: (f: Partial<ContactFilters>) => void;
  loadContacts: () => Promise<void>;
  saveContact: (data: Partial<Contact>, id?: number) => Promise<Contact>;
  deleteContact: (id: number) => Promise<void>;

  loadFunnels: () => Promise<void>;
  saveFunnel: (data: { name: string; description: string; stages?: Partial<Stage>[] }, id?: number) => Promise<Funnel>;
  deleteFunnel: (id: number) => Promise<void>;

  loadDeals: (funnelId?: number) => Promise<void>;
  saveDeal: (data: Partial<Deal>, id?: number) => Promise<Deal>;
  moveDeal: (id: number, stageId: number) => Promise<void>;
  deleteDeal: (id: number) => Promise<void>;

  loadPosts: () => Promise<void>;
  savePost: (data: Partial<Post>, id?: number) => Promise<Post>;
  deletePost: (id: number) => Promise<void>;
}

const upsert = <T extends { id: number }>(list: T[], item: T) =>
  list.some((x) => x.id === item.id) ? list.map((x) => (x.id === item.id ? item : x)) : [item, ...list];

export const useCrm = create<CrmState>((set, get) => {
  const withLoading = async (key: string, fn: () => Promise<void>) => {
    set({ loading: { ...get().loading, [key]: true } });
    try { await fn(); } finally { set({ loading: { ...get().loading, [key]: false } }); }
  };

  return {
    channels: [], funnels: [], contacts: [], contactTotal: 0, deals: [], posts: [], loading: {},
    contactFilters: { q: "", status: "", channel_id: "", tag: "" },

    async loadReference() { await Promise.all([get().loadChannels(), get().loadFunnels()]); },

    // ---- channels
    loadChannels: () => withLoading("channels", async () => set({ channels: await api.get<Channel[]>("/channels") })),
    async saveChannel(data, id) {
      const ch = id ? await api.patch<Channel>(`/channels/${id}`, data) : await api.post<Channel>("/channels", data);
      await get().loadChannels(); // refresh computed stats
      return ch;
    },
    async deleteChannel(id) {
      await api.del(`/channels/${id}`);
      set({ channels: get().channels.filter((c) => c.id !== id) });
    },

    // ---- contacts
    setContactFilters(f) { set({ contactFilters: { ...get().contactFilters, ...f } }); },
    loadContacts: () => withLoading("contacts", async () => {
      const r = await api.get<{ items: Contact[]; total: number }>("/contacts", { ...get().contactFilters, limit: 500 });
      set({ contacts: r.items, contactTotal: r.total });
    }),
    async saveContact(data, id) {
      const c = id ? await api.patch<Contact>(`/contacts/${id}`, data) : await api.post<Contact>("/contacts", data);
      set({ contacts: upsert(get().contacts, c), contactTotal: get().contactTotal + (id ? 0 : 1) });
      return c;
    },
    async deleteContact(id) {
      await api.del(`/contacts/${id}`);
      set({ contacts: get().contacts.filter((c) => c.id !== id), contactTotal: get().contactTotal - 1 });
    },

    // ---- funnels
    loadFunnels: () => withLoading("funnels", async () => set({ funnels: await api.get<Funnel[]>("/funnels") })),
    async saveFunnel(data, id) {
      const f = id ? await api.put<Funnel>(`/funnels/${id}`, data) : await api.post<Funnel>("/funnels", data);
      const exists = get().funnels.some((x) => x.id === f.id);
      set({ funnels: exists ? get().funnels.map((x) => (x.id === f.id ? f : x)) : [...get().funnels, f] });
      return f;
    },
    async deleteFunnel(id) {
      await api.del(`/funnels/${id}`);
      set({ funnels: get().funnels.filter((f) => f.id !== id), deals: get().deals.filter((d) => d.funnel_id !== id) });
    },

    // ---- deals
    loadDeals: (funnelId) => withLoading("deals", async () =>
      set({ deals: await api.get<Deal[]>("/deals", { funnel_id: funnelId }) })),
    async saveDeal(data, id) {
      const d = id ? await api.patch<Deal>(`/deals/${id}`, data) : await api.post<Deal>("/deals", data);
      set({ deals: upsert(get().deals, d) });
      return d;
    },
    async moveDeal(id, stageId) {
      const before = get().deals;
      // optimistic update so the card moves instantly
      set({ deals: before.map((d) => (d.id === id ? { ...d, stage_id: stageId } : d)) });
      try {
        const d = await api.patch<Deal>(`/deals/${id}`, { stage_id: stageId });
        set({ deals: upsert(get().deals, d) });
      } catch (e) {
        set({ deals: before });
        throw e;
      }
    },
    async deleteDeal(id) {
      await api.del(`/deals/${id}`);
      set({ deals: get().deals.filter((d) => d.id !== id) });
    },

    // ---- posts
    loadPosts: () => withLoading("posts", async () => set({ posts: await api.get<Post[]>("/posts") })),
    async savePost(data, id) {
      const p = id ? await api.patch<Post>(`/posts/${id}`, data) : await api.post<Post>("/posts", data);
      set({ posts: upsert(get().posts, p) });
      return p;
    },
    async deletePost(id) {
      await api.del(`/posts/${id}`);
      set({ posts: get().posts.filter((p) => p.id !== id) });
    },
  };
});

export const channelName = (channels: Channel[], id: number | null | undefined) =>
  channels.find((c) => c.id === id)?.name ?? "—";
