// Global toast store.
//
// Single source of truth for stacked notifications shown via the
// `<GToastStack/>` outlet (mounted once in AppShell). Views call
// `toast({ title, sub?, tone? })` to push; toasts auto-dismiss after
// `ttlMs` (default 4 s) or on explicit `dismiss(id)`.
//
// Why a zustand store instead of context? Toasts are fired from deep
// trees (composer, message hover actions, channel header actions),
// often from inside `useEffect` / event handlers. Reaching them
// through context would force every caller into a hook + re-render
// chain; a store lets us export a plain `toast(...)` function that
// callers can use without subscribing.
//
// Replaces the previous `window.alert("… coming soon")` and the
// `window.alert(error.message)` patterns scattered across the app.

import { create } from "zustand";

import type { GToastTone } from "../components/Goofy";

export interface ToastInput {
  /** Headline (Fredoka). */
  title: string;
  /** Optional sub-line. */
  sub?: string;
  /** Visual tone — defaults to `"info"`. */
  tone?: GToastTone;
  /** Override the default 4 s auto-dismiss. `0` keeps the toast pinned. */
  ttlMs?: number;
}

export interface ToastEntry extends ToastInput {
  id: string;
}

interface ToastState {
  toasts: ToastEntry[];
  push: (input: ToastInput) => string;
  dismiss: (id: string) => void;
}

function makeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push(input) {
    const id = makeId();
    const ttl = input.ttlMs ?? 4_000;
    set((s) => ({ toasts: [...s.toasts, { id, ...input }] }));
    if (ttl > 0) {
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
      }, ttl);
    }
    return id;
  },
  dismiss(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));

/**
 * Fire-and-forget toast push. Use this from event handlers, async
 * callbacks, or anywhere outside a component subscription. Returns the
 * generated id so callers can pin/dismiss the toast manually.
 */
export function toast(input: ToastInput): string {
  return useToasts.getState().push(input);
}

/**
 * Convenience: surface an error from a `try/catch` block with a sensible
 * default title. Use as `try { … } catch (e) { errorToast(e, "Couldn't save"); }`.
 */
export function errorToast(err: unknown, fallbackTitle = "Something went wrong"): string {
  const msg = err instanceof Error ? err.message : String(err);
  return toast({ tone: "danger", title: fallbackTitle, sub: msg });
}

/**
 * Convenience: drop a "coming soon" placeholder toast. Reads in the
 * same tone the previous `alert("… coming soon")` calls did, but
 * non-blocking and dismissible.
 */
export function comingSoonToast(label: string): string {
  return toast({
    tone: "ai",
    title: `${label} — coming soon`,
    sub: "We're still putting this together. Check back in a bit.",
  });
}
