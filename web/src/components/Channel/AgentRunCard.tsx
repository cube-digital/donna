// Agent-run card — port of `design-source/project/channel.jsx:4-55`.
//
// Renders the violet-tinted card that replaces the text body of a
// message whose kind === "agent-run". The shape lives on
// `Message.metadata` (see types/index.ts → AgentRunMetadata) and is
// computed client-side in `state/messages.ts::classifyBody`. When a
// real `AgentRun` model lands on the backend we lift `metadata` to a
// serializer field and delete the JSON-body parse — the rendering
// here doesn't need to change.
//
// Collapse / expand
// ─────────────────
// Defaults expanded. The "Hide steps" / "Show steps" link in the run
// head toggles visibility of the run body. The run footer (memory
// chips + actions) stays visible regardless because the design keeps
// the action affordance reachable when collapsed.
//
// Footer wrapping
// ───────────────
// The footer carries an unbounded number of memory chips plus two
// action buttons. We `flex-wrap` so chips reflow under their own row
// when the card is narrow; the `Memory used` label, chips, and the
// action buttons share a single flex line via `gap-2` + a `flex-1`
// spacer that becomes the wrap pressure point.
//
// Thought stripe
// ──────────────
// The original `.run-thought::before` rendered a 3px ai-coloured bar
// along the line's left edge. Tailwind can't paint pseudo-element
// content, so we render an explicit `<span/>` instead — same visual,
// but a real DOM node we can size with utilities.

import { useState } from "react";

import type { AgentRunStep, Message } from "../../types";
import { Ic } from "../Ui/Ic";

interface AgentRunCardProps {
  msg: Message;
}

function stepIcon(kind: AgentRunStep["kind"]) {
  switch (kind) {
    case "read":
      return <Ic.doc />;
    case "write":
      return <Ic.edit />;
    case "think":
      return <Ic.brain />;
    case "tool":
    default:
      return <Ic.bolt />;
  }
}

function RunStep({ step }: { step: AgentRunStep }) {
  const stateColor =
    step.state === "running" ? "text-ai" : "text-text-3";
  return (
    <div className="flex items-center gap-2.5 py-1 text-[12.5px] text-text-1">
      <div className="w-[22px] h-[22px] rounded-sm grid place-items-center bg-[oklch(0.74_0.16_282/0.12)] text-ai shrink-0">
        {stepIcon(step.kind)}
      </div>
      <span className="text-text-0">{step.label}</span>
      {step.meta ? (
        <span className="text-text-3 text-[11.5px] font-mono">{step.meta}</span>
      ) : null}
      {step.state ? (
        <span
          className={`ml-auto text-[10.5px] uppercase tracking-[0.04em] ${stateColor}`}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 bg-current align-middle" />
          {step.state}
        </span>
      ) : null}
    </div>
  );
}

export default function AgentRunCard({ msg }: AgentRunCardProps) {
  const [expanded, setExpanded] = useState(true);
  const meta = msg.metadata ?? {};
  const status = meta.status ?? "done";
  const steps = meta.steps ?? [];
  const memory = meta.memoryTouched ?? [];
  const attachments = meta.attachments ?? [];

  const agentName = msg.author_agent?.name ?? "agent";
  const ledClass =
    status === "running"
      ? "bg-ai animate-led-blink"
      : "bg-ok";

  return (
    <div className="mt-1.5 border border-ai-glow rounded-lg run-card-bg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ai-glow">
        <span className="text-[11px] tracking-[0.04em] uppercase font-semibold text-ai">
          Agent run
        </span>
        {meta.summary ? (
          <>
            <span className="text-text-3">·</span>
            <span className="text-[12.5px] text-text-1">{meta.summary}</span>
          </>
        ) : null}
        <span className="flex-1" />
        <span className="flex items-center gap-1.5 text-[11.5px] text-text-2">
          <span
            className={`w-[7px] h-[7px] rounded-full ${ledClass}`}
          />
          {status === "running" ? "Running" : "Completed"}
        </span>
        <button
          type="button"
          className="text-text-3 text-[11px] hover:text-text-0"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Hide steps" : "Show steps"}
        </button>
      </div>

      {expanded ? (
        <div className="px-3 pt-2 pb-2.5">
          {meta.streaming && meta.currentThought ? (
            <div className="flex items-start gap-2 py-1.5 text-text-2 italic text-[12.5px]">
              <span className="w-[3px] self-stretch rounded-[2px] bg-ai shrink-0" />
              <span className="flex-1">
                {meta.currentThought}
                <span className="thought-dots" />
              </span>
            </div>
          ) : null}

          {steps.length > 0 ? (
            <div className="flex flex-col gap-1 py-1">
              {steps.map((step, i) => (
                <RunStep key={i} step={step} />
              ))}
            </div>
          ) : null}

          {meta.output ? (
            <div className="mt-2 px-3 py-2.5 bg-bg-1 border border-border-soft rounded-lg text-text-0 text-[13px] leading-[1.55]">
              {meta.output}
            </div>
          ) : null}

          {attachments.length > 0
            ? attachments.map((a, i) => (
                <div
                  key={i}
                  className="mt-2 flex items-center gap-2 border border-border-soft bg-bg-1 rounded-md px-2.5 py-1.5 w-max max-w-full"
                >
                  <span className="text-text-2">
                    <Ic.link />
                  </span>
                  <span className="text-text-0 text-[12.5px]">{a.name}</span>
                  {a.size ? (
                    <span className="text-text-3 text-[11.5px]">{a.size}</span>
                  ) : null}
                </div>
              ))
            : null}
        </div>
      ) : null}

      {/* Footer is always rendered when there's memory OR actions to show.
          The design keeps the "Continue with agent" / "Add to context"
          buttons available even when steps are collapsed. */}
      <div className="flex flex-wrap items-center gap-2 px-3 pt-2 mt-1 border-t border-ai-glow">
        {memory.length > 0 ? (
          <>
            <span className="text-[11px] text-text-3 tracking-[0.04em] uppercase">
              Memory used
            </span>
            {memory.map((m, i) => (
              <span
                key={i}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-bg-2 border border-border-soft text-[11px] text-text-2 font-mono"
              >
                <Ic.brain width={11} height={11} />
                {m}
              </span>
            ))}
          </>
        ) : null}
        <span className="flex-1" />
        <button
          type="button"
          className="text-[11.5px] text-text-2 px-2 py-0.5 rounded-md hover:bg-bg-2 hover:text-text-0"
          onClick={() => alert("Add to context coming soon")}
        >
          Add to context
        </button>
        <button
          type="button"
          className="text-[11.5px] text-ai bg-ai-bg px-2 py-0.5 rounded-md"
          onClick={() => alert(`Continue with ${agentName} coming soon`)}
        >
          Continue with {agentName}
        </button>
      </div>
    </div>
  );
}
