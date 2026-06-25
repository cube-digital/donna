// ReactionBar — chips under a Message.
//
// Click an existing chip = toggle own reaction. Click "+" = open EmojiPicker.

import { useRef, useState } from "react";

import { addReaction, removeReaction } from "../../api/chat";
import { EMOJIS_BY_CODE } from "../../lib/emojis";
import { useMessages } from "../../state/messages";
import type { Message, ReactionAgg } from "../../types";
import { EmojiPicker } from "./EmojiPicker";

interface ReactionBarProps {
  message: Message;
}

export function ReactionBar({ message }: ReactionBarProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const addBtnRef = useRef<HTMLButtonElement>(null);
  const applyAdded = useMessages((s) => s.applyReactionAdded);
  const applyRemoved = useMessages((s) => s.applyReactionRemoved);

  const reactions = message.reactions ?? [];

  const toggle = async (r: ReactionAgg) => {
    if (r.by_me) {
      applyRemoved(message.channel, message.id, r.emoji, true);
      try {
        await removeReaction(message.id, r.emoji);
      } catch {
        applyAdded(message.channel, message.id, r.emoji, true); // rollback
      }
    } else {
      applyAdded(message.channel, message.id, r.emoji, true);
      try {
        await addReaction(message.id, r.emoji);
      } catch {
        applyRemoved(message.channel, message.id, r.emoji, true); // rollback
      }
    }
  };

  const openPicker = () => {
    setAnchor(addBtnRef.current?.getBoundingClientRect() ?? null);
    setPickerOpen(true);
  };

  if (reactions.length === 0 && !pickerOpen) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-1 mt-1">
      {reactions.map((r) => {
        const u = EMOJIS_BY_CODE[r.emoji]?.unicode ?? r.emoji;
        return (
          <button
            key={r.emoji}
            type="button"
            onClick={() => toggle(r)}
            title={`:${r.emoji}:`}
            className={
              "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[12px] " +
              (r.by_me
                ? "border-ai bg-ai-bg text-text-0"
                : "border-ink/30 bg-bg-1 hover:bg-bg-2")
            }
          >
            <span className="text-[14px] leading-none">{u}</span>
            <span className="tabular-nums">{r.count}</span>
          </button>
        );
      })}
      <button
        ref={addBtnRef}
        type="button"
        onClick={openPicker}
        className="inline-flex items-center px-1.5 py-0.5 rounded-full border border-dashed border-ink/30 text-[12px] text-text-2 hover:bg-bg-2 hover:text-text-0"
        title="Add reaction"
      >
        +
      </button>
      <EmojiPicker
        open={pickerOpen}
        anchorRect={anchor}
        onClose={() => setPickerOpen(false)}
        onPick={(e) => {
          setPickerOpen(false);
          // Optimistic + POST.
          applyAdded(message.channel, message.id, e.code, true);
          addReaction(message.id, e.code).catch(() =>
            applyRemoved(message.channel, message.id, e.code, true),
          );
        }}
      />
    </div>
  );
}
