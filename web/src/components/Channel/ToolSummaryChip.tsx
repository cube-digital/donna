// Plan 13 §1.2 — Haiku tool-batch summary chip.
//
// Listens on `agent.tool_summary` and displays the most recent
// one-line summary for the active channel (or run). Auto-fades a few
// seconds after the next agent message lands, since the summary
// becomes stale once the model produces its own reply.

import { useEffect, useState } from "react";

import { getChatWs } from "../../lib/ws";

interface Props {
  /** Optional — when set, only show summaries for this channel. The
   *  server emits these on the agent_run group today (no channel id),
   *  so this is reserved for a future hook when the WS payload widens. */
  channelId?: string;
}

const STALE_AFTER_MS = 12_000;

export function ToolSummaryChip({ channelId: _channelId }: Props) {
  const [summary, setSummary] = useState<{ text: string; count: number } | null>(
    null,
  );

  useEffect(() => {
    const off = getChatWs().on("agent.tool_summary", (e) => {
      setSummary({ text: e.summary, count: e.tool_count });
    });
    return off;
  }, []);

  useEffect(() => {
    if (!summary) return;
    const t = setTimeout(() => setSummary(null), STALE_AFTER_MS);
    return () => clearTimeout(t);
  }, [summary]);

  if (!summary) return null;

  return (
    <div className="my-1 inline-flex items-center gap-1 rounded-md bg-[var(--ai-bg)] px-2 py-0.5 text-[10px] text-[color:var(--ai-deep)]">
      <span className="font-semibold uppercase tracking-wide">
        {summary.count} tool{summary.count === 1 ? "" : "s"}
      </span>
      <span className="opacity-80">·</span>
      <span>{summary.text}</span>
    </div>
  );
}
