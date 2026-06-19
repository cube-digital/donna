"""ToolRegistry — name→DonnaTool lookup + describe_all + freeze().

**Two-tier model:**

- ``GLOBAL_REGISTRY`` is the singleton populated at chat app boot
  (``chat/apps.py ready()``). Connectors / extensions register
  their tools here. After boot ``freeze()`` is called → subsequent
  ``register()`` raises ``RegistryFrozenError`` (openfang pattern —
  blocks runtime tool injection from compromised deps or plugin
  loaders).
- Per-turn registries (built by ``factory.build_registry``) are
  short-lived, scoped to a single channel + draft policy, and are
  NOT frozen — they're constructed fresh on every turn.

Plain English: the global list of "what tools exist in this process"
is locked once everyone has registered. The "what tools this channel
should see" filter is rebuilt per turn from the locked list.
"""
from __future__ import annotations

from typing import Iterable

from .base import DonnaTool


class RegistryFrozenError(RuntimeError):
    """Raised when register() is called after freeze()."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, DonnaTool] = {}
        self._frozen = False

    def register(self, *tools: DonnaTool) -> None:
        if self._frozen:
            raise RegistryFrozenError(
                "ToolRegistry is frozen — register at app boot only. "
                "Attempted: " + ", ".join(t.name for t in tools)
            )
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def freeze(self) -> None:
        """Lock the registry. Subsequent register() calls raise."""
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def get(self, name: str) -> DonnaTool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def describe_all(self) -> list[dict]:
        return [t.describe() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """Build a per-turn registry containing only the named tools
        from this one. The subset is NOT frozen — channel/draft gating
        rebuilds it every turn."""
        wanted = set(names)
        sub = ToolRegistry()
        for n, tool in self._tools.items():
            if n in wanted:
                sub._tools[n] = tool
        return sub


# Module-level singleton. Populated by donna.chat.apps.ChatConfig.ready().
GLOBAL_REGISTRY = ToolRegistry()

