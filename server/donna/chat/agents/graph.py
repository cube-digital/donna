"""run_graph — the agent loop. entry → agent ↻ dispatcher (max 6 rounds).

Plain Python loop — no framework. Round cap prevents runaway tool
churn; on exhaustion we synthesize an apologetic final_text so the
turn always produces a message.
"""
from __future__ import annotations

import logging

from donna.chat.agents.nodes.conversation_agent import ConversationAgent
from donna.chat.agents.nodes.tool_dispatcher import ToolDispatcher
from donna.chat.agents.state.builder import AgentState
from donna.chat.agents.tools.base import ToolContext
from donna.chat.agents.tools.registry import ToolRegistry


logger = logging.getLogger(__name__)


MAX_ROUNDS = 6


def run_graph(
    state: AgentState,
    ctx: ToolContext,
    registry: ToolRegistry,
    *,
    agent: ConversationAgent | None = None,
    dispatcher: ToolDispatcher | None = None,
    max_rounds: int = MAX_ROUNDS,
) -> AgentState:
    agent = agent or ConversationAgent()
    dispatcher = dispatcher or ToolDispatcher()

    state = agent(state, ctx, registry)
    while state.pending_tool_calls and state.rounds < max_rounds:
        state.rounds += 1
        state = dispatcher(state, ctx, registry)
        state = agent(state, ctx, registry)

    if state.pending_tool_calls and state.rounds >= max_rounds:
        logger.warning("agent_round_cap_exhausted", extra={"rounds": state.rounds})
        state.final_text = (
            "I tried several lookups but couldn't pull together a confident "
            "answer in the time I had. Could you narrow the question or "
            "point me at a specific document?"
        )
        state.pending_tool_calls = []

    if state.final_text is None:
        # Defensive: agent returned no tool_calls and no text. Synthesize.
        state.final_text = "Sorry — I don't have anything useful to say on that."
    return state
