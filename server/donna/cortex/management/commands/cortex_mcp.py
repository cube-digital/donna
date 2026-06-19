"""Run the Cortex MCP server over stdio.

Usage from Claude Code's config file (~/.claude/mcp.json typically):

    {
      "mcpServers": {
        "donna-cortex": {
          "command": "uv",
          "args": [
            "run", "python", "-m", "django", "cortex_mcp"
          ],
          "cwd": "/path/to/donna/server",
          "env": {
            "DJANGO_SETTINGS_MODULE": "donna.settings",
            "DONNA_MCP_WORKSPACE_ID": "<uuid>"
          }
        }
      }
    }
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Cortex MCP server over stdio."

    def handle(self, *args, **options) -> None:
        from donna.cortex.mcp import run_stdio
        run_stdio()
