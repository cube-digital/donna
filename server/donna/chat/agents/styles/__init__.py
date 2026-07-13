"""Plan 13 §1.1 — output styles.

External markdown files swap the agent's tone overlay per channel.
Bundled styles live alongside this module under ``bundled/``; a
workspace can pin a style via ``AgentSession.config["output_style"]``
(slug matching a bundled file's ``name`` frontmatter key, or just the
filename stem).

Discovery is module-load-once: bundled markdown is parsed at boot and
cached in ``BUNDLED_STYLES``. Edits require a worker restart — there is
no hot reload because styles seed prompt caching and silent
inconsistency between workers is worse than a redeploy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


_BUNDLED_DIR = Path(__file__).parent / "bundled"


@dataclass(frozen=True)
class OutputStyle:
    """One named tone overlay.

    ``body`` is the prose appended to the system prompt; ``description``
    is shown in admin UIs / pickers but never reaches the model.
    """

    name: str
    description: str
    body: str


def _parse(path: Path) -> OutputStyle:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm) or {}
    else:
        meta, body = {}, text
    name = meta.get("name") or path.stem
    return OutputStyle(
        name=name,
        description=meta.get("description", ""),
        body=body.strip(),
    )


def load_bundled_styles() -> Mapping[str, OutputStyle]:
    if not _BUNDLED_DIR.is_dir():
        return {}
    return {s.name: s for s in (_parse(p) for p in sorted(_BUNDLED_DIR.glob("*.md")))}


BUNDLED_STYLES: Mapping[str, OutputStyle] = load_bundled_styles()


def resolve(slug: str | None) -> OutputStyle | None:
    """Return the style for ``slug`` (None if missing / unset)."""
    if not slug:
        return None
    return BUNDLED_STYLES.get(slug)
