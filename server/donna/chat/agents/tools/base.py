"""Tool base — DonnaTool, ToolContext, ToolResult, Tainted marker.

Each tool subclasses ``DonnaTool`` and declares: ``name``,
``description``, ``args_model`` (Pydantic). The dispatcher uses
``describe()`` to feed ``LLMProvider.chat(tools=...)`` and ``run()``
to execute when the LLM emits a matching tool_call.

**Tainted** is a type marker (NewType) — strings that originated from
external content (cortex/email/webhook) carry the marker so dangerous
tools can refuse them at the dispatcher boundary. The marker is
type-level only — runtime cost = zero — and is currently advisory in
this Q&A slice (full enforcement lands in A2 drafting).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, NewType

from pydantic import BaseModel


# Type marker — see module docstring + 00j §A0.
Tainted = NewType("Tainted", str)


@dataclass(frozen=True)
class ToolContext:
    """Per-turn execution context passed into every tool's ``run()``."""

    workspace: Any            # donna.workspaces.models.Workspace
    user: Any | None          # User | None (None for scheduled/system invocations)
    channel: Any              # donna.chat.models.Channel
    agent_session: Any        # donna.chat.models.AgentSession


@dataclass(frozen=True)
class ToolResult:
    """Uniform tool return shape."""

    payload: Any = None
    error: str | None = None

    @classmethod
    def fail(cls, msg: str) -> "ToolResult":
        return cls(error=msg)


class DonnaTool(ABC):
    """Base class — subclass + set the four ClassVars + implement ``run()``."""

    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    # Per-tool wall-clock budget. Default 120s; macro/delegating tools
    # override (PrepareContext: 300; FinalizeDraft: 240). Dispatcher
    # enforces via concurrent.futures.
    timeout_s: ClassVar[int] = 120

    # Taint policy. False = dispatcher REFUSES if any argument carries
    # the Tainted marker. Tools that legitimately consume external text
    # (DrafterNode, summarizers) set True and own the sanitization
    # contract internally. Q&A read tools are taint_safe=True by default
    # because they only return content; they don't act on it.
    taint_safe: ClassVar[bool] = True

    def announce(self, args: BaseModel) -> str:
        """User-facing status line emitted to the run stream (not chat)."""
        return f"Running {self.name}…"

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must return a ToolResult (never raise on
        recoverable errors — return ToolResult.fail(msg) so the LLM
        sees the error and can self-correct)."""

    def describe(self) -> dict:
        """OpenAI/Anthropic tool schema — feeds LLMProvider.chat(tools=...)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }
