// Per-channel typing presence.
//
// The chat consumer (`server/donna/chat/consumers.py::_action_typing` and
// `chat_typing`) emits a `typing` event with `{channel_id, user_id}` each
// time someone is actively composing. The event is fire-and-forget — no
// matching "stopped typing" frame — so we age every entry out client-side
// after `TYPING_TTL_MS`.
//
// We keep this store deliberately small and separate from `state/messages.ts`:
//   - messages.ts already has a large surface area; pollution makes its
//     reconcile logic harder to reason about
//   - typing is purely ephemeral; nothing on disk, nothing to reconcile
//
// API
// ───
// `markTyping(channelId, userId)`       — called from Channel.tsx when a
//                                          `typing` WS event arrives.
// `setCurrentUserId(id)`                — track the signed-in user id so
//                                          we can filter "you are typing"
//                                          out of the indicator. Captured
//                                          from the WS `connected` event.
// `useTypingUserIds(channelId)`         — selector hook returning the
//                                          current set of typing user ids
//                                          for a channel (Set is cloned on
//                                          every mutation so React picks up
//                                          the change). Self id is filtered
//                                          inside the hook.
//
// Per-entry timers
// ─────────────────
// We hold a per-(channel, user) `setTimeout` handle in a module-local map;
// each new `markTyping` call clears the prior timeout and starts a fresh
// 4-second timer. When it fires, the user is removed from the channel's
// set. The timer map is never exposed — callers only see the state.

import { create } from "zustand";

const TYPING_TTL_MS = 4_000;

interface PresenceState {
  /** Channel id → set of user ids currently typing. */
  typingByChannel: Record<string, Set<string>>;
  /** The signed-in user's id (captured from WS `connected`). */
  currentUserId: string | null;
  markTyping(channelId: string, userId: string): void;
  setCurrentUserId(id: string | null): void;
  /** Remove a single user from a channel's typing set. */
  _expire(channelId: string, userId: string): void;
}

// Module-scoped timer registry — keyed `${channelId}:${userId}`.
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export const usePresence = create<PresenceState>((set, get) => ({
  typingByChannel: {},
  currentUserId: null,

  setCurrentUserId: (id) => set({ currentUserId: id }),

  markTyping: (channelId, userId) => {
    const key = `${channelId}:${userId}`;
    const prev = timers.get(key);
    if (prev) clearTimeout(prev);
    const handle = setTimeout(() => {
      timers.delete(key);
      get()._expire(channelId, userId);
    }, TYPING_TTL_MS);
    timers.set(key, handle);

    set((s) => {
      const existing = s.typingByChannel[channelId] ?? new Set<string>();
      // Already present + timer was refreshed above — no need to re-render.
      if (existing.has(userId)) return s;
      const next = new Set(existing);
      next.add(userId);
      return {
        typingByChannel: { ...s.typingByChannel, [channelId]: next },
      };
    });
  },

  _expire: (channelId, userId) => {
    set((s) => {
      const existing = s.typingByChannel[channelId];
      if (!existing || !existing.has(userId)) return s;
      const next = new Set(existing);
      next.delete(userId);
      const out = { ...s.typingByChannel };
      if (next.size === 0) {
        delete out[channelId];
      } else {
        out[channelId] = next;
      }
      return { typingByChannel: out };
    });
  },
}));

/**
 * Selector hook — array of user ids currently typing in `channelId`,
 * with the current user filtered out. Returns a stable empty-array
 * reference when nobody (other than self) is typing so React's
 * `Object.is` change detection skips downstream renders.
 *
 * Note: zustand's default equality is `===`. We rebuild the array each
 * call by necessity (filter), but the empty case short-circuits to a
 * module-level constant.
 */
export function useTypingUserIds(channelId: string | undefined): string[] {
  return usePresence((s) => {
    if (!channelId) return EMPTY_ARRAY;
    const set = s.typingByChannel[channelId];
    if (!set || set.size === 0) return EMPTY_ARRAY;
    const me = s.currentUserId;
    const out: string[] = [];
    for (const id of set) {
      if (id === me) continue;
      out.push(id);
    }
    if (out.length === 0) return EMPTY_ARRAY;
    return out;
  });
}

// Stable reference so the selector returns `===` between renders when
// nobody is typing — avoids spurious downstream re-renders.
const EMPTY_ARRAY: string[] = [];
