"""Interactive UI entrypoint.

The interactive experience is now a Textual TUI. The CLI still imports
``AgentREPL`` for backwards compatibility, but the implementation
delegates to ``DeepAgentTUI``.
"""

from __future__ import annotations

from typing import Any

from .config import AppConfig
from .tui.app import DeepAgentTUI


class AgentREPL:
    """Compatibility wrapper used by ``deepagent_azure_cli.cli.main()``."""

    def __init__(self, agent: Any, config: AppConfig):
        self.agent = agent
        self.config = config

    def run(self) -> None:
        # Thin shim on purpose: callers keep using AgentREPL while TUI evolves underneath.
        DeepAgentTUI(self.agent, self.config).run()
