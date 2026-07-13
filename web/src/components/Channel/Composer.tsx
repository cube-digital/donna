// Composer — port of `design-source/project/channel.jsx:189-218`.
//
// The send path uses the WebSocket (`ChatWsClient.send("send_message")`)
// so that the consumer broadcasts the echo back into the channel
// group. We optimistically insert a placeholder message immediately
// keyed by a generated `client_msg_id`; the WS echo runs through the
// messages store's `appendFromEvent`, which sees the same id and
// reconciles in-place.
//
// Why optimistic + WS echo (not WS-only): the WS round-trip is fast
// in practice, but typing the message into the list immediately is
// the difference between a chat that feels responsive and one that
// feels laggy. The `client_msg_id` dedupe makes the swap invisible.
//
// Global `/` shortcut: focuses the textarea — but ONLY when no input/
// textarea/contenteditable is already focused, so we don't steal the
// keystroke from the search box etc.
//
// Format buttons (Bold / Italic / etc.) are visual stubs — markdown
// shortcuts aren't wired in v1. They're kept in the DOM with proper
// tabindex so keyboard users can still tab through them and so the
// design layout reads correctly.
//
// Goofy chrome
// ────────────
// The composer is split into two sticker surfaces:
//   - the format toolbar (its own border-ink + shadow strip)
//   - the `<GField/>` note-card holding the textarea + footer slot
// This mirrors the design source's channel composer (see Showcase).
// When `ai` is true (Personal chat), the GField switches to the
// grape-tinted variant.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { getChatWs } from "../../lib/ws";
import { useMessages } from "../../state/messages";
import { comingSoonToast } from "../../state/toasts";
import {
  GChip,
  GlyphSlot,
} from "../Goofy";
import type { Message } from "../../types";
import { EmojiPicker } from "./EmojiPicker";
import { MentionPopover } from "./MentionPopover";
import type { MentionCandidate } from "../../api/chat";

interface ComposerProps {
  channelId: string;
  /** Optional placeholder override (e.g. "Message Donna…" in Personal). */
  placeholder?: string;
  /** Switch to the AI-tinted GField variant (Personal chat). */
  ai?: boolean;
}

// Rate-limit `typing` emits so we don't send one frame per keystroke.
// The consumer side has no debounce; emitting once per ~1s is plenty
// for the receiver TTL window (4s).
const TYPING_EMIT_MS = 1_500;

function newClientMsgId(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  // RFC4122 v4-ish fallback for older environments.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function isTypingInsideField(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

const FMT_TYPO_BTN =
  "w-6 h-6 grid place-items-center text-text-4 hover:text-text-2 transition-colors";

export default function Composer({
  channelId,
  placeholder,
  ai = false,
}: ComposerProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastTypingEmitRef = useRef(0);
  const optimisticInsert = useMessages((s) => s.optimisticInsert);

  const send = useCallback(() => {
    const body = text.trim();
    if (!body) return;
    const clientMsgId = newClientMsgId();

    // Optimistic placeholder. We mint a fake id starting with `tmp-` so
    // the React key is stable until the WS echo replaces it; the
    // reconcile step keys on `client_msg_id`, not on the id.
    const draft: Message = {
      id: `tmp-${clientMsgId}`,
      channel: channelId,
      body,
      // Without a /me endpoint we can't fill `author_user` here; we
      // leave it null so the row renders as "You" via the fallback in
      // <Message/>. The real REST/WS echo will hydrate the author.
      author_user: null,
      author_agent: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      client_msg_id: clientMsgId,
    };
    optimisticInsert(channelId, draft);

    getChatWs().send("send_message", {
      channel_id: channelId,
      body,
      client_msg_id: clientMsgId,
    });

    setText("");
  }, [channelId, optimisticInsert, text]);

  const onKeyDown = (ev: KeyboardEvent<HTMLTextAreaElement>) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.nativeEvent.isComposing) {
      ev.preventDefault();
      send();
    }
  };

  // `/` global shortcut → focus the textarea, unless the user is
  // already typing somewhere else.
  useEffect(() => {
    const onKey = (ev: globalThis.KeyboardEvent) => {
      if (ev.key !== "/" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (isTypingInsideField(document.activeElement)) return;
      ev.preventDefault();
      textareaRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Emoji picker state.
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [emojiAnchor, setEmojiAnchor] = useState<DOMRect | null>(null);
  const emojiBtnRef = useRef<HTMLButtonElement | null>(null);

  // Mention popover state.
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const mentionAnchorRef = useRef<{ start: number; end: number } | null>(null);

  function detectMentionAtCursor(value: string, cursor: number): { start: number; q: string } | null {
    // Walk back from cursor to find an `@` not preceded by an alnum/underscore.
    let i = cursor - 1;
    while (i >= 0) {
      const ch = value[i];
      if (ch === "@") {
        const prev = i > 0 ? value[i - 1] : "";
        if (prev && /[A-Za-z0-9_]/.test(prev)) return null;
        return { start: i, q: value.slice(i + 1, cursor) };
      }
      if (/\s/.test(ch)) return null;
      i--;
    }
    return null;
  }

  const onComposerChange = (next: string, cursor: number) => {
    setText(next);
    const m = detectMentionAtCursor(next, cursor);
    if (m) {
      mentionAnchorRef.current = { start: m.start, end: cursor };
      setMentionQuery(m.q);
    } else {
      mentionAnchorRef.current = null;
      setMentionQuery(null);
    }
  };

  const onMentionSelect = (c: MentionCandidate) => {
    const anchor = mentionAnchorRef.current;
    if (!anchor) {
      setMentionQuery(null);
      return;
    }
    const before = text.slice(0, anchor.start);
    const after = text.slice(anchor.end);
    const insertion = `@${c.handle} `;
    const next = before + insertion + after;
    setText(next);
    setMentionQuery(null);
    mentionAnchorRef.current = null;
    requestAnimationFrame(() => {
      if (!textareaRef.current) return;
      const pos = (before + insertion).length;
      textareaRef.current.selectionStart = pos;
      textareaRef.current.selectionEnd = pos;
      textareaRef.current.focus();
    });
  };

  const insertAtCursor = useCallback(
    (snippet: string) => {
      const el = textareaRef.current;
      if (!el) {
        setText(text + snippet);
        return;
      }
      const start = el.selectionStart ?? text.length;
      const end = el.selectionEnd ?? text.length;
      const next = text.slice(0, start) + snippet + text.slice(end);
      setText(next);
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        const pos = start + snippet.length;
        textareaRef.current.selectionStart = pos;
        textareaRef.current.selectionEnd = pos;
        textareaRef.current.focus();
      });
    },
    [text],
  );

  const openEmoji = () => {
    setEmojiAnchor(emojiBtnRef.current?.getBoundingClientRect() ?? null);
    setEmojiOpen(true);
  };

  const ready = text.trim().length > 0;
  const ph =
    placeholder ?? "Message — Shift+Enter for newline, / to focus, @ to mention";

  // Char / line count — only show when the user has actually typed
  // anything; otherwise the row is empty (the design doesn't carve out
  // permanent space for it).
  const charCount = text.length;
  const lineCount = text ? text.split("\n").length : 0;

  void ai;

  return (
    <div className="mx-auto mt-2 mb-4 max-w-[720px] w-[calc(100%-36px)] border border-border-soft rounded-[14px] bg-bg-1 overflow-visible relative">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => {
          const next = e.target.value;
          const cursor = e.target.selectionStart ?? next.length;
          onComposerChange(next, cursor);
          const now = Date.now();
          if (
            next.length > 0 &&
            now - lastTypingEmitRef.current > TYPING_EMIT_MS
          ) {
            lastTypingEmitRef.current = now;
            getChatWs().send("typing", { channel_id: channelId });
          }
        }}
        onKeyDown={onKeyDown}
        placeholder={ph}
        rows={2}
        className="w-full resize-none bg-transparent px-4 py-3 text-[14px] text-text-0 placeholder:text-text-3 outline-none border-0"
      />
      <MentionPopover
        channelId={channelId}
        query={mentionQuery ?? ""}
        open={mentionQuery !== null}
        onSelect={onMentionSelect}
        onClose={() => setMentionQuery(null)}
        inputRef={textareaRef}
      />

      {charCount > 0 ? (
        <div className="px-4 -mt-1 mb-1 text-[11px] text-text-3 flex gap-2 tabular-nums">
          <span>
            {charCount} char{charCount === 1 ? "" : "s"}
          </span>
          {lineCount > 1 ? <span>· {lineCount} lines</span> : null}
        </div>
      ) : null}

      <div className="flex items-center gap-3 px-3 py-2 border-t border-border-soft">
        <div className="flex items-center gap-[13px] text-text-4">
          <button type="button" className={FMT_TYPO_BTN} aria-label="Bold" title="Bold">
            <b className="text-[14px]">B</b>
          </button>
          <button type="button" className={FMT_TYPO_BTN} aria-label="Italic" title="Italic">
            <i className="text-[14px]">I</i>
          </button>
          <button type="button" className={FMT_TYPO_BTN} aria-label="Link" title="Link">
            <GlyphSlot name="link" size={15} />
          </button>
          <button type="button" className={FMT_TYPO_BTN} aria-label="Code" title="Code">
            <GlyphSlot name="bolt" size={15} />
          </button>
          <button
            ref={emojiBtnRef}
            type="button"
            aria-label="Insert emoji"
            title="Emoji"
            onClick={openEmoji}
            className={FMT_TYPO_BTN}
          >
            <GlyphSlot name="smile" size={15} />
          </button>
          <button
            type="button"
            className={FMT_TYPO_BTN}
            aria-label="Mention"
            title="Mention"
            onClick={() => comingSoonToast("Agent mention")}
          >
            <GlyphSlot name="at" size={15} />
          </button>
          <button
            type="button"
            className={FMT_TYPO_BTN}
            aria-label="Attach"
            title="Attach"
            onClick={() => comingSoonToast("Attachments")}
          >
            <GlyphSlot name="plus" size={15} />
          </button>
        </div>

        <span className="flex-1" />

        <GChip variant="ai" size="sm" className="!border-0 !shadow-none font-semibold text-[11px]">
          <GlyphSlot name="sparkle" size={12} className="text-white" />
          Agents on standby
        </GChip>

        <button
          type="button"
          onClick={send}
          disabled={!ready}
          aria-label="Send message"
          title="Send"
          className={
            "w-8 h-8 grid place-items-center rounded-[9px] border border-border-soft bg-bg-1 transition-opacity " +
            (ready
              ? "text-ai-deep hover:opacity-90"
              : "text-text-3 cursor-not-allowed")
          }
        >
          <GlyphSlot name="send" size={16} />
        </button>
      </div>

      <EmojiPicker
        open={emojiOpen}
        anchorRect={emojiAnchor}
        onClose={() => setEmojiOpen(false)}
        onPick={(e) => {
          insertAtCursor(e.unicode);
          setEmojiOpen(false);
        }}
      />
    </div>
  );
}
