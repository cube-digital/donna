// ThreadPanel — replies for a single parent message.
//
// Mounted in the right rail when the user clicks "Reply" on a Message.
// Load replies via REST on open; new replies arrive via the same
// `chat.message.created` WS event with `parent_id` set, routed in lib/ws
// (see App-level wiring).

import { useEffect, useRef, useState } from "react";

import { postReply } from "../../api/chat";
import { useMessages } from "../../state/messages";
import type { Message } from "../../types";

interface ThreadPanelProps {
  parent: Message;
  onClose: () => void;
}

export function ThreadPanel({ parent, onClose }: ThreadPanelProps) {
  const replies = useMessages((s) => s.threads[parent.id] ?? []);
  const loading = useMessages((s) => s.threadsLoading[parent.id]);
  const load = useMessages((s) => s.loadThread);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    load(parent.id);
  }, [parent.id, load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [replies.length]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = body.trim();
    if (!text) return;
    setBusy(true);
    try {
      await postReply(parent.channel, parent.id, text);
      setBody("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="flex flex-col h-full border-l-2 border-ink bg-bg-0 w-[380px] max-w-[40vw]">
      <header className="flex items-center justify-between px-3 py-2 border-b-2 border-dashed border-ink/40">
        <div className="font-display font-semibold text-[14px]">Thread</div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close thread"
          className="text-text-2 hover:text-text-0 text-[18px] leading-none"
        >
          ×
        </button>
      </header>
      <div className="flex-1 overflow-y-auto p-3">
        <div className="border-b border-dashed border-ink/30 pb-3 mb-3">
          <div className="text-[12px] text-text-2 mb-1">
            {parent.author_user?.full_name || parent.author_user?.email ||
              parent.author_agent?.name || "Unknown"}
          </div>
          <div className="text-[14px] whitespace-pre-wrap">{parent.body}</div>
        </div>
        {loading && <div className="text-[12px] text-text-2">Loading…</div>}
        {replies.map((r) => (
          <div key={r.id} className="mb-2.5">
            <div className="text-[12px] text-text-2">
              {r.author_user?.full_name || r.author_user?.email ||
                r.author_agent?.name || "Unknown"}
            </div>
            <div className="text-[13px] whitespace-pre-wrap">{r.body}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={send} className="border-t-2 border-dashed border-ink/40 p-2 flex gap-2">
        <input
          type="text"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Reply…"
          className="flex-1 px-2 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-bg-1 outline-none focus:ring-2 focus:ring-ai/30"
        />
        <button
          type="submit"
          disabled={busy || !body.trim()}
          className="px-3 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-ai text-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
