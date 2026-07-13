// Plan 13 §1.3 + §1.5 — HIL question/answer picker.
//
// When the agent posts a `Message(kind=question)`, this component
// replaces the message body with an inline picker (or a free-text
// textarea when no options were supplied). Submitting calls
// `POST /api/v1/chat/messages/<id>/answer/`; the resume task fires
// server-side and the channel will receive the agent's next message
// via the normal `message.created` WS event.

import { useState } from "react";

import { answerQuestion } from "../../api/chat";
import type { Message, QuestionOption } from "../../types";

interface Props {
  message: Message;
  /** Optional callback invoked after a successful submit (e.g. to
   *  optimistically de-render the picker before the server WS confirms). */
  onAnswered?: (answer: { value: string | null; text: string | null }) => void;
}

export function QuestionPicker({ message, onAnswered }: Props) {
  const options: QuestionOption[] = message.question_options ?? [];
  const isFreeText =
    options.length === 0 ||
    (options.length === 1 && options[0].value === "free_text");
  const expired = message.answer_payload?.expired === true;
  const alreadyAnswered =
    message.answer_payload !== null && message.answer_payload !== undefined;

  const [selected, setSelected] = useState<string | null>(
    isFreeText ? null : options[0]?.value ?? null,
  );
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (expired) {
    return (
      <div className="rounded-md bg-bg-1 px-3 py-2 text-xs text-text-2">
        This question timed out.
      </div>
    );
  }

  if (alreadyAnswered) {
    const text = message.answer_payload?.text;
    const value = message.answer_payload?.value;
    return (
      <div className="rounded-md bg-bg-1 px-3 py-2 text-xs text-text-2">
        Answered: <span className="font-medium text-text-1">{text || value}</span>
      </div>
    );
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const body = isFreeText
        ? { value: null, text: text.trim() }
        : { value: selected, text: text.trim() || null };
      if (isFreeText && !body.text) {
        setError("Please type an answer.");
        setSubmitting(false);
        return;
      }
      await answerQuestion(message.id, body);
      onAnswered?.({
        value: body.value ?? null,
        text: body.text ?? null,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit answer.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-border-soft bg-bg-1 px-3 py-2">
      <div className="text-sm text-text-1">{message.body}</div>

      {!isFreeText && (
        <div className="flex flex-wrap gap-1.5" role="radiogroup">
          {options.map((opt) => {
            const active = selected === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setSelected(opt.value)}
                title={opt.description}
                className={
                  "rounded-full px-3 py-1 text-xs font-medium transition " +
                  (active
                    ? "bg-[var(--ai-bg)] text-[color:var(--ai-deep)]"
                    : "bg-bg-0 text-text-2 hover:text-text-1")
                }
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      )}

      {isFreeText ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type your answer…"
          rows={2}
          className="w-full resize-none rounded-md bg-bg-0 px-2 py-1.5 text-sm text-text-1 outline-none focus:ring-1 focus:ring-[color:var(--ai)]"
        />
      ) : (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add context (optional)"
          rows={2}
          className="w-full resize-none rounded-md bg-bg-0 px-2 py-1.5 text-sm text-text-1 outline-none focus:ring-1 focus:ring-[color:var(--ai)]"
        />
      )}

      {error && <div className="text-xs text-red-500">{error}</div>}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={submitting || (!isFreeText && !selected)}
          className="rounded-md bg-[var(--ai)] px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
        >
          {submitting ? "Sending…" : "Send answer"}
        </button>
      </div>
    </div>
  );
}
