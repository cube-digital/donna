"""OCR utility functions.

Shared helpers used across OCR strategies.
"""

from __future__ import annotations


def markdown_to_html(text: str) -> str:
    """Convert markdown text to HTML with full GFM support.

    Uses ``markdown-it-py`` with tables, strikethrough, footnotes,
    definition lists, and task lists enabled.

    Args:
        text: Markdown-formatted text.

    Returns:
        HTML string with proper ``<table>`` elements.
    """
    from markdown_it import MarkdownIt
    from mdit_py_plugins.deflist import deflist_plugin
    from mdit_py_plugins.footnote import footnote_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = (
        MarkdownIt()
        .enable("table")
        .enable("strikethrough")
        .use(footnote_plugin)
        .use(deflist_plugin)
        .use(tasklists_plugin)
    )
    return md.render(text)
