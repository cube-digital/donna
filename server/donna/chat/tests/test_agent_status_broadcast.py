"""Plan 13 §8.2 — broadcast_agent_status WS emission tests.

We test the broadcaster's ``async_to_sync(group_send)`` payload shape
against a stubbed channel layer. The integration that the frontend chip
renders these events lives in the React-side tests (deferred).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from donna.chat.services import broadcast_agent_status


class _FakeLayer:
    """Records ``group_send`` calls so the test can introspect them.

    Implemented as a SYNC callable so we can also patch out
    ``async_to_sync`` to a passthrough — Channels' real async_to_sync
    needs an event loop hookup the test environment doesn't have."""

    def __init__(self, raise_exc=None):
        self.calls: list[tuple[str, dict]] = []
        self.raise_exc = raise_exc

    def group_send(self, group, payload):  # noqa: D401
        if self.raise_exc:
            raise self.raise_exc
        self.calls.append((group, payload))


def _passthrough(fn):
    return fn


class BroadcastAgentStatusTests(SimpleTestCase):
    def _channel(self):
        return SimpleNamespace(id="ch-1")

    def _session(self):
        return SimpleNamespace(id="ag-1")

    def _patches(self, layer):
        return [
            patch("donna.chat.services.get_channel_layer", return_value=layer),
            patch("donna.chat.services.async_to_sync", side_effect=_passthrough),
        ]

    def test_no_layer_is_a_noop(self):
        # Must not raise when Channels isn't configured (test env).
        with patch("donna.chat.services.get_channel_layer", return_value=None):
            broadcast_agent_status(
                channel=self._channel(),
                agent_session=self._session(),
                state="drafting",
            )

    def test_payload_includes_state_and_ids(self):
        layer = _FakeLayer()
        patches = self._patches(layer)
        for p in patches:
            p.start()
        try:
            broadcast_agent_status(
                channel=self._channel(),
                agent_session=self._session(),
                state="waiting_on_user",
                detail="Send to Alice?",
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(len(layer.calls), 1)
        _group, message = layer.calls[0]
        self.assertEqual(message["type"], "chat.agent.status")
        payload = message["payload"]
        self.assertEqual(payload["state"], "waiting_on_user")
        self.assertEqual(payload["channel_id"], "ch-1")
        self.assertEqual(payload["session_id"], "ag-1")
        self.assertEqual(payload["detail"], "Send to Alice?")

    def test_broadcast_failure_is_silent(self):
        """A broken channel layer must NEVER bubble up — status is UX,
        not business-critical."""
        layer = _FakeLayer(raise_exc=RuntimeError("broker dead"))
        patches = self._patches(layer)
        for p in patches:
            p.start()
        try:
            # No assertion — only that the call returns cleanly.
            broadcast_agent_status(
                channel=self._channel(),
                agent_session=self._session(),
                state="idle",
            )
        finally:
            for p in patches:
                p.stop()
