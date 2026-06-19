"""Chat app config.

``ready()`` populates the GLOBAL agent tool registry and freezes it
(openfang pattern, 2026-06-14). After this hook, no more tool
registration is possible — defense against runtime tool injection
from compromised deps or plugin loaders.
"""
from __future__ import annotations

import logging

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class ChatConfig(AppConfig):
    name = "donna.chat"
    label = "chat"

    def ready(self) -> None:
        try:
            from donna.chat.agents.tools.factory import register_qa_tools
            from donna.chat.agents.tools.registry import GLOBAL_REGISTRY

            register_qa_tools()
            # A2 will append draft tool registration here BEFORE freeze.
            GLOBAL_REGISTRY.freeze()
        except Exception:  # noqa: BLE001 — never block app boot on registry wire
            logger.exception("agent_global_registry_boot_failed")
