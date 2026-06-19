"""Conversation agent — LLM call producing either tool_calls or final text.

Invariant (docupal v10): one message kind per turn — tool_calls XOR
final text. If the model emits text alongside tool_calls, we keep the
tool_calls and discard the text (it always re-emits after the tool
results come back).
"""
from __future__ import annotations

import logging

from donna.chat.agents.prompts import build_system_prompt
from donna.chat.agents.state.builder import AgentState
from donna.chat.agents.tools.base import ToolContext
from donna.chat.agents.tools.registry import ToolRegistry
from donna.core.llm.factory import LLMFactory


logger = logging.getLogger(__name__)


# Default model — overridable via AgentSession.config["model"] (A3).
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"


class ConversationAgent:
    def __init__(self, llm=None, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL
        self._llm = llm or LLMFactory.create(model=self._model)

    def __call__(
        self,
        state: AgentState,
        ctx: ToolContext,
        registry: ToolRegistry,
    ) -> AgentState:
        system_prompt = build_system_prompt(ctx)
        try:
            resp = self._llm.chat(
                messages=state.messages,
                system_prompt=system_prompt,
                tools=registry.describe_all(),
                tool_choice="auto",
                temperature=0.3,
            )
        except Exception:  # noqa: BLE001
            logger.exception("conversation_agent_chat_failed")
            state.final_text = (
                "I hit an unexpected error reaching the language model. "
                "Try again in a moment."
            )
            state.pending_tool_calls = []
            return state

        if resp.tool_calls:
            # Assistant turn carrying tool calls. We MUST keep content
            # consistent — when content is None/empty, omit the key for
            # providers that reject empty-content assistant turns alongside
            # tool_calls. LiteLLM tolerates either.
            state.messages.append({
                "role": "assistant",
                "content": resp.content if isinstance(resp.content, str) else "",
                "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
            })
            state.pending_tool_calls = list(resp.tool_calls)
        else:
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            state.messages.append({"role": "assistant", "content": text})
            state.final_text = text
            state.pending_tool_calls = []
        return state
