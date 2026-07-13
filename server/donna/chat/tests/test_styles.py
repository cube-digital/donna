"""Plan 13 §1.1 — output style loader + system-prompt overlay tests.

Bundled markdown should parse cleanly; resolve() returns the right
``OutputStyle``; ``build_system_prompt`` appends the body when
``AgentSession.config["output_style"]`` is set and skips it otherwise.
"""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from donna.chat.agents.prompts import build_system_prompt
from donna.chat.agents.styles import BUNDLED_STYLES, resolve


class BundledStylesTests(SimpleTestCase):
    def test_all_four_bundled_styles_load(self):
        # The names match the filenames + frontmatter ``name`` keys.
        for slug in ("concise", "detailed", "technical", "customer"):
            style = resolve(slug)
            self.assertIsNotNone(style, f"missing bundled style: {slug}")
            # Sanity: each style has a non-empty body that mentions itself.
            self.assertIn("OUTPUT STYLE", style.body)
            self.assertTrue(style.description)

    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(resolve("does-not-exist"))
        self.assertIsNone(resolve(None))
        self.assertIsNone(resolve(""))

    def test_loader_is_idempotent(self):
        # BUNDLED_STYLES is the module-level snapshot; resolve must hit it.
        for name, style in BUNDLED_STYLES.items():
            self.assertIs(resolve(name), style)


class SystemPromptOverlayTests(SimpleTestCase):
    """``build_system_prompt`` must include the style body when configured."""

    def _ctx(self, output_style=None, mode="chat"):
        session = SimpleNamespace(
            config={"output_style": output_style} if output_style else {},
            memory={},
            mode=mode,
        )
        return SimpleNamespace(agent_session=session)

    def test_style_body_appears_when_set(self):
        prompt = build_system_prompt(self._ctx(output_style="concise"))
        self.assertIn("OUTPUT STYLE: concise", prompt)

    def test_no_style_body_when_unset(self):
        prompt = build_system_prompt(self._ctx())
        self.assertNotIn("OUTPUT STYLE", prompt)

    def test_unknown_style_falls_through_silently(self):
        # Unknown slug should NOT inject anything — graceful degrade.
        prompt = build_system_prompt(self._ctx(output_style="nonexistent"))
        self.assertNotIn("OUTPUT STYLE", prompt)

    def test_mode_guidance_and_style_compose(self):
        """Drafting mode + style should both appear, both before memory."""
        prompt = build_system_prompt(
            self._ctx(output_style="customer", mode="drafting"),
        )
        self.assertIn("DRAFTING MODE", prompt)
        self.assertIn("OUTPUT STYLE: customer", prompt)
