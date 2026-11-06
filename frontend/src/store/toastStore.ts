import { create } from "zustand";

export interface Toast { id: number; message: string; tone: "info" | "error" | "success" }

interface ToastState {
  toasts: Toast[];
  push: (message: string, tone?: Toast["tone"]) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;
export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push(message, tone = "info") {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, message, tone }] });
    setTimeout(() => get().dismiss(id), tone === "error" ? 6000 : 3000);
  },
  dismiss(id) { set({ toasts: get().toasts.filter((t) => t.id !== id) }); },
}));

/** Show an error toast for any thrown value. */
export const toastError = (e: unknown) =>
  useToasts.getState().push(e instanceof Error ? e.message : String(e), "error");
