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

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { getChatWs } from "../../lib/ws";
import { useMessages } from "../../state/messages";
import { Ic } from "../Ui/Ic";
import type { Message } from "../../types";

interface ComposerProps {
  channelId: string;
  /** Optional placeholder override (e.g. "Message Donna…" in Personal). */
  placeholder?: string;
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

const FMT_BTN =
  "w-6 h-6 grid place-items-center rounded-sm hover:bg-bg-2 hover:text-text-1";
const FOOT_BTN =
  "w-6 h-6 grid place-items-center rounded-md text-text-2 hover:bg-bg-2 hover:text-text-0";

export default function Composer({ channelId, placeholder }: ComposerProps) {
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

  const ready = text.trim().length > 0;
  const ph =
    placeholder ?? "Message — Shift+Enter for newline, / to focus, @ to mention";

  // Char / line count — only show when the user has actually typed
  // anything; otherwise the row is empty (the design doesn't carve out
  // permanent space for it).
  const charCount = text.length;
  const lineCount = text ? text.split("\n").length : 0;

  return (
    <div className="mx-[18px] mt-2 mb-3.5 border border-border-strong rounded-xl bg-bg-1 shadow-soft">
      <div className="flex items-center gap-0.5 px-2.5 py-1.5 border-b border-border-soft text-text-3 text-[12px]">
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Bold"
          tabIndex={0}
          title="Bold"
        >
          <b>B</b>
        </button>
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Italic"
          tabIndex={0}
          title="Italic"
        >
          <i>I</i>
        </button>
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Strikethrough"
          tabIndex={0}
          title="Strikethrough"
        >
          <s>S</s>
        </button>
        <div className="w-px h-4 bg-border-soft mx-1" />
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Code"
          tabIndex={0}
          title="Code"
        >
          <span className="font-mono text-[11px]">{"</>"}</span>
        </button>
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Quote"
          tabIndex={0}
          title="Quote"
        >
          &raquo;
        </button>
        <button
          type="button"
          className={FMT_BTN}
          aria-label="Link"
          tabIndex={0}
          title="Link"
        >
          <Ic.link />
        </button>
        <div className="w-px h-4 bg-border-soft mx-1" />
        <button
          type="button"
          className={FMT_BTN}
          aria-label="List"
          tabIndex={0}
          title="List"
        >
          ≣
        </button>
      </div>

      <div className="px-3.5 py-3 min-h-[44px] text-text-0 text-[13px]">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => {
            const next = e.target.value;
            setText(next);
            // Throttle typing emits — see TYPING_EMIT_MS comment above.
            const now = Date.now();
            if (next.length > 0 && now - lastTypingEmitRef.current > TYPING_EMIT_MS) {
              lastTypingEmitRef.current = now;
              getChatWs().send("typing", { channel_id: channelId });
            }
          }}
          onKeyDown={onKeyDown}
          placeholder={ph}
          rows={2}
          className="block w-full resize-none bg-transparent text-text-0 text-[13px] leading-[1.55] min-h-[28px] placeholder:text-text-3"
        />
        {charCount > 0 ? (
          <div className="mt-1 text-[11px] text-text-3 flex gap-2 tabular-nums">
            <span>
              {charCount} char{charCount === 1 ? "" : "s"}
            </span>
            {lineCount > 1 ? <span>· {lineCount} lines</span> : null}
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-1 px-2 pt-1.5 pb-2">
        <button
          type="button"
          className={FOOT_BTN}
          title="Attach file"
          aria-label="Attach file"
          onClick={() => alert("Attachments coming soon")}
        >
          <Ic.plus />
        </button>
        <button
          type="button"
          className={FOOT_BTN}
          title="Mention agent"
          aria-label="Mention agent"
          onClick={() => alert("Agent mention coming soon")}
        >
          <Ic.at />
        </button>
        <button
          type="button"
          className={FOOT_BTN}
          title="Emoji"
          aria-label="Emoji"
          onClick={() => alert("Emoji picker coming soon")}
        >
          <Ic.smile />
        </button>
        <div className="flex items-center gap-1.5 ml-1 px-2 h-6 rounded-md text-[11.5px] text-ai bg-ai-bg border border-ai-glow">
          <Ic.sparkle width={12} height={12} />
          Agents on standby
        </div>
        <div className="flex-1" />
        <button
          type="button"
          className={
            ready
              ? "w-7 h-7 rounded-md grid place-items-center bg-text-0 text-bg-0"
              : "w-7 h-7 rounded-md grid place-items-center bg-bg-3 text-text-1"
          }
          onClick={send}
          disabled={!ready}
          aria-label="Send message"
          title="Send"
        >
          <Ic.send width={14} height={14} />
        </button>
      </div>
    </div>
  );
}
