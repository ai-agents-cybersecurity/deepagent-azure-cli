"""
Interactive REPL (Read-Eval-Print Loop) for the coding assistant.

Provides a rich terminal experience with:
  - Streaming output from the agent
  - Human-in-the-loop approval prompts (with proper LangGraph resume)
  - Session management (new / resume)
  - Graceful interrupt handling (Ctrl+C)
"""

from __future__ import annotations

import uuid
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.theme import Theme

from .config import AppConfig

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
THEME = Theme(
    {
        "agent": "bold cyan",
        "user": "bold green",
        "tool": "bold yellow",
        "error": "bold red",
        "info": "dim",
    }
)


class AgentREPL:
    """Interactive REPL that wraps a DeepAgent graph."""

    def __init__(self, agent: Any, config: AppConfig):
        self.agent = agent
        self.config = config
        self.console = Console(theme=THEME)
        self.thread_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def _print_welcome(self) -> None:
        self.console.print(
            Panel(
                "[agent]DeepAgent Azure CLI[/agent]\n"
                f"Model: [info]{self.config.azure.deployment_name}[/info] "
                f"@ [info]{self.config.azure.endpoint}[/info]\n"
                f"Working dir: [info]{self.config.agent.root_dir}[/info]\n"
                f"Session: [info]{self.thread_id[:8]}...[/info]\n\n"
                "Type your request, or:\n"
                "  [info]/new[/info]    — start a new session\n"
                "  [info]/quit[/info]   — exit\n"
                "  [info]/config[/info] — show current configuration",
                title="[agent]Welcome[/agent]",
                border_style="cyan",
            )
        )

    def _print_config(self) -> None:
        lines = [
            f"Azure endpoint:    {self.config.azure.endpoint}",
            f"Deployment:        {self.config.azure.deployment_name}",
            f"API version:       {self.config.azure.api_version}",
            f"Root dir:          {self.config.agent.root_dir}",
            f"Approve shell:     {self.config.agent.approve_shell}",
            f"Approve writes:    {self.config.agent.approve_writes}",
            f"Search enabled:    {self.config.agent.enable_search}",
            f"Checkpoint DB:     {self.config.agent.checkpoint_db or 'in-memory'}",
            f"Session thread:    {self.thread_id}",
        ]
        self.console.print(
            Panel("\n".join(lines), title="Configuration", border_style="cyan")
        )

    def _print_tool_call(self, tool_name: str, tool_input: Any) -> None:
        """Display a tool call being made by the agent."""
        input_str = str(tool_input)
        if len(input_str) > 300:
            input_str = input_str[:300] + "..."
        self.console.print(f"\n[tool]Tool:[/tool] {tool_name}")
        self.console.print(f"[info]{input_str}[/info]")

    def _print_agent_response(self, content: str) -> None:
        """Render agent markdown response."""
        if content and content.strip():
            self.console.print()
            self.console.print(Markdown(content))

    # ------------------------------------------------------------------
    # Human-in-the-loop approval
    # ------------------------------------------------------------------
    def _prompt_approval(self, tool_name: str, tool_args: dict) -> bool:
        """
        Ask the user to approve a tool call.

        Returns True if approved, False if rejected.
        """
        self.console.print(
            Panel(
                f"[tool]{tool_name}[/tool]\n\n"
                f"{self._format_tool_args(tool_name, tool_args)}",
                title="[yellow]Approval Required[/yellow]",
                border_style="yellow",
            )
        )

        choice = Prompt.ask(
            "[yellow]Approve? (y/n)[/yellow]",
            choices=["y", "n"],
            default="y",
        )

        return choice == "y"

    def _format_tool_args(self, tool_name: str, args: dict) -> str:
        """Format tool arguments for human review."""
        if tool_name == "execute":
            cmd = args.get("command", args.get("cmd", str(args)))
            return f"Command:\n```\n{cmd}\n```"
        elif tool_name in ("write_file", "edit_file"):
            path = args.get("path", args.get("file_path", "?"))
            content = args.get("content", args.get("new_content", ""))
            if isinstance(content, str):
                preview = content[:500] + ("..." if len(content) > 500 else "")
            else:
                preview = str(content)[:500]
            return f"File: {path}\n```\n{preview}\n```"
        else:
            return str(args)[:500]

    # ------------------------------------------------------------------
    # Stream event processing
    # ------------------------------------------------------------------
    def _process_stream_events(self, stream) -> None:
        """Process streamed events from the LangGraph agent."""
        for event in stream:
            # LangGraph stream_mode="updates" yields {node_name: state_update}
            for node_name, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue

                messages = state_update.get("messages", [])
                for msg in messages:
                    self._render_message(msg)

    def _render_message(self, msg: Any) -> None:
        """Render a single message from the stream."""
        # Show tool calls on AI messages
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                self._print_tool_call(name, args)

        # Show message content
        content = getattr(msg, "content", None)
        if not content:
            return

        msg_type = getattr(msg, "type", None)
        if msg_type == "ai":
            self._print_agent_response(str(content))
        elif msg_type == "tool":
            result_preview = str(content)
            if len(result_preview) > 200:
                result_preview = result_preview[:200] + "..."
            self.console.print(f"[info]  Result: {result_preview}[/info]")

    # ------------------------------------------------------------------
    # Main agent invocation with interrupt handling
    # ------------------------------------------------------------------
    def _invoke(self, user_message: str) -> None:
        """Send a message to the agent, handling interrupts for approval."""
        invoke_config = {"configurable": {"thread_id": self.thread_id}}

        try:
            # First invocation with the user message
            stream = self.agent.stream(
                {"messages": [{"role": "user", "content": user_message}]},
                config=invoke_config,
                stream_mode="updates",
            )
            self._process_stream_events(stream)

            # After streaming, check for pending interrupts and handle them
            self._handle_pending_interrupts(invoke_config)

        except KeyboardInterrupt:
            self.console.print("\n[info]Interrupted. Agent stopped.[/info]")
        except Exception as e:
            error_msg = str(e)
            # Provide a friendlier message for common errors
            if "401" in error_msg or "Unauthorized" in error_msg:
                self.console.print(
                    "\n[error]Authentication failed.[/error] "
                    "Check your AZURE_OPENAI_API_KEY."
                )
            elif "404" in error_msg or "NotFound" in error_msg:
                self.console.print(
                    "\n[error]Deployment not found.[/error] "
                    "Check your AZURE_OPENAI_DEPLOYMENT_NAME."
                )
            elif "429" in error_msg or "RateLimitError" in error_msg:
                self.console.print(
                    "\n[error]Rate limited.[/error] "
                    "Wait a moment and try again."
                )
            else:
                self.console.print(f"\n[error]Error: {error_msg}[/error]")

    def _handle_pending_interrupts(self, invoke_config: dict) -> None:
        """
        Check for and handle any pending interrupts from the graph.

        LangGraph's interrupt_on pauses the graph when a tool is about to
        execute. We check the graph state, prompt the user for approval,
        and resume the graph with the decision.
        """
        try:
            from langgraph.types import Command
        except ImportError:
            # Older langgraph — interrupts may work differently
            return

        max_interrupt_rounds = 20  # Safety limit to avoid infinite loops

        for _ in range(max_interrupt_rounds):
            try:
                state = self.agent.get_state(invoke_config)
            except Exception:
                break

            # Check if there are pending tasks (interrupts)
            # LangGraph stores interrupted tasks in state.tasks
            tasks = getattr(state, "tasks", None)
            if not tasks:
                break

            # Find tasks that have interrupts
            has_interrupt = False
            for task in tasks:
                interrupts = getattr(task, "interrupts", None)
                if not interrupts:
                    continue

                has_interrupt = True
                for interrupt_value in interrupts:
                    # The interrupt value contains info about the pending tool call
                    value = getattr(interrupt_value, "value", interrupt_value)

                    # Extract tool info from the interrupt
                    tool_name = "unknown"
                    tool_args = {}
                    if isinstance(value, dict):
                        tool_name = value.get("tool_name", value.get("name", "unknown"))
                        tool_args = value.get("args", value.get("input", {}))

                    # Prompt user
                    approved = self._prompt_approval(tool_name, tool_args)

                    if approved:
                        # Resume the graph — let the tool execute
                        resume_stream = self.agent.stream(
                            Command(resume="approve"),
                            config=invoke_config,
                            stream_mode="updates",
                        )
                        self._process_stream_events(resume_stream)
                    else:
                        # Reject — resume with rejection
                        self.console.print("[info]Action rejected.[/info]")
                        resume_stream = self.agent.stream(
                            Command(resume="reject"),
                            config=invoke_config,
                            stream_mode="updates",
                        )
                        self._process_stream_events(resume_stream)

            if not has_interrupt:
                break

    # ------------------------------------------------------------------
    # REPL loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Start the interactive REPL loop."""
        self._print_welcome()

        while True:
            try:
                self.console.print()
                user_input = Prompt.ask("[user]You[/user]")

                if not user_input or not user_input.strip():
                    continue

                # Handle REPL commands
                cmd = user_input.strip().lower()
                if cmd in ("/quit", "/exit", "/q"):
                    self.console.print("[info]Goodbye![/info]")
                    break
                elif cmd == "/new":
                    self.thread_id = str(uuid.uuid4())
                    self.console.print(
                        f"[info]New session: {self.thread_id[:8]}...[/info]"
                    )
                    continue
                elif cmd == "/config":
                    self._print_config()
                    continue
                elif cmd == "/help":
                    self.console.print(
                        "[info]/new    — start a new session\n"
                        "/config — show current configuration\n"
                        "/quit   — exit\n"
                        "/help   — show this help[/info]"
                    )
                    continue

                # Send to agent
                self._invoke(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[info]Ctrl+C — type /quit to exit[/info]")
            except EOFError:
                self.console.print("\n[info]Goodbye![/info]")
                break
