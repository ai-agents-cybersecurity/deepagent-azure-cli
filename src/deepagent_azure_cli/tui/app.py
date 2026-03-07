"""Textual TUI application for DeepAgent Azure CLI.

Replaces the Rich REPL with a Claude Code-like interface:
- scrollable timeline
- input bar
- streaming updates
- HITL approvals (Approve/Reject)
- session commands: /new, /init, /quit, /config

Hard requirement: never print raw JSON / Python-literal blocks.
"""

from __future__ import annotations

import contextlib
import io
import uuid
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, TextArea

from ..config import AppConfig
from ..interaction_logger import DailyInteractionLogger, extract_token_usage, merge_token_usage
from .events import (
    ApprovalRequestEvent,
    AssistantEvent,
    SystemEvent,
    SystemLevel,
    ToolCallEvent,
    ToolResultEvent,
    UserEvent,
)
from .hitl import build_decisions, find_pending_approval, approval_ui_text
from .renderer import summarize_tool_call, summarize_tool_result
from .widgets import ApprovalDock, Timeline


class DeepAgentTUI(App[None]):
    """Main Textual app."""

    CSS = """
    Screen {
        layout: vertical;
    }

    /* Prompt editor is docked at bottom above footer. */
    #prompt {
        dock: bottom;
        height: 10;
    }

    Footer {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "copy_last_assistant", "Copy last response"),
        ("ctrl+t", "copy_timeline", "Copy timeline"),
    ]

    def __init__(self, agent: Any, config: AppConfig) -> None:
        super().__init__()
        self.agent = agent
        self.config = config
        self.thread_id: str = str(uuid.uuid4())
        self.status: str = "Ready"

        self._invoke_config: dict[str, Any] = {"configurable": {"thread_id": self.thread_id}}
        self._approval_pending: bool = False
        self._pending_request_count: int = 0
        self._active_agent: Any = self.agent
        self._init_agent: Any | None = None

        # Keep our JSONL interaction logger separate from Textual's internal logger.
        self._interaction_logger = DailyInteractionLogger()
        self._active_turn_id: str | None = None
        self._active_turn_tokens: dict[str, int | None] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        self._turn_seen_usage_keys: set[str] = set()

        self._last_assistant_text: str = ""
        self._timeline_plain_lines: list[str] = []

    # -------------------------- UI composition --------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container():
            yield Timeline(id="timeline")
        yield ApprovalDock()
        yield TextArea("", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(ApprovalDock).display = False
        self._post_system_welcome()
        self._update_title()
        prompt = self.query_one("#prompt", TextArea)
        if not prompt.disabled:
            prompt.focus()

    def _periodic_flush(self) -> None:
        self._interaction_logger.flush()

    # ----------------------------- Clipboard -----------------------------

    def action_copy_last_assistant(self) -> None:
        text = self._last_assistant_text.strip()
        self._copy_text_to_clipboard(text, empty_message="No assistant response to copy yet.")

    def action_copy_timeline(self) -> None:
        text = "\n\n".join(line for line in self._timeline_plain_lines if line.strip())
        self._copy_text_to_clipboard(text, empty_message="Timeline is empty.")

    def _copy_text_to_clipboard(self, text: str, *, empty_message: str) -> None:
        if not text:
            self._emit(SystemEvent(text=empty_message, level=SystemLevel.WARNING))
            return

        try:
            copy_fn = getattr(self, "copy_to_clipboard", None)
            if not callable(copy_fn):
                self._emit(SystemEvent(
                    text="Clipboard copy is not supported by this Textual version.",
                    level=SystemLevel.WARNING,
                ))
                return
            copy_fn(text)
            self._emit(SystemEvent(text="Copied to clipboard.", level=SystemLevel.INFO))
        except Exception as e:
            self._emit(SystemEvent(text=f"Clipboard copy failed: {e}", level=SystemLevel.ERROR))

    # ------------------------------ Timeline helpers ------------------------------

    def _timeline(self) -> Timeline:
        return self.query_one("#timeline", Timeline)

    def _emit(self, event) -> None:
        self._timeline().add_event(event)

    def _update_title(self) -> None:
        self.title = (
            f"DeepAgent Azure CLI | {self.config.azure.deployment_name} "
            f"| Session {self.thread_id[:8]}..."
        )

    def _post_system_welcome(self) -> None:
        self._emit(SystemEvent(
            text=(
                f"DeepAgent Azure CLI | "
                f"Model: {self.config.azure.deployment_name} @ {self.config.azure.endpoint} | "
                f"Dir: {self.config.agent.root_dir} | "
                f"Session: {self.thread_id[:8]}... | "
                f"Commands: /new /init /config /quit /help"
            ),
            level=SystemLevel.INFO,
        ))

    def _post_config(self) -> None:
        lines = [
            f"Azure endpoint:    {self.config.azure.endpoint}",
            f"Deployment:        {self.config.azure.deployment_name}",
            f"API version:       {self.config.azure.api_version}",
            f"Root dir:          {self.config.agent.root_dir}",
            f"Approve shell:     {self.config.agent.approve_shell}",
            f"Approve writes:    {self.config.agent.approve_writes}",
            f"Reasoning effort:  {self.config.agent.reasoning_effort}",
            f"Search enabled:    {self.config.agent.enable_search}",
            f"Checkpoint DB:     {self.config.agent.checkpoint_db or 'in-memory'}",
            f"Session thread:    {self.thread_id}",
        ]
        self._emit(SystemEvent(text="\n".join(lines), level=SystemLevel.INFO))

    def _set_idle(self) -> None:
        self.status = "Ready"
        self._approval_pending = False
        prompt = self.query_one("#prompt", TextArea)
        prompt.disabled = False
        prompt.focus()

    # ----------------------------- Input handling -----------------------------

    def on_text_area_submitted(self, event) -> None:
        """Handle Enter in the prompt TextArea (Textual >=0.40)."""
        # Fallback for older Textual versions that don't emit this event
        pass

    def on_key(self, event) -> None:
        """Handle key presses; submit on Enter."""
        if event.key == "enter":
            prompt = self.query_one("#prompt", TextArea)
            if prompt.disabled:
                return
            text = prompt.text.strip()
            if not text:
                return
            prompt.clear()
            self._handle_input(text)

    def _handle_input(self, text: str) -> None:
        cmd = text.strip()

        # Check for REPL commands
        c = cmd.lower()
        if c in ("/quit", "/exit", "/q"):
            self.exit()
            return
        if c.startswith("/"):
            self._handle_command(cmd)
            return

        # Regular user message
        self._emit(UserEvent(text=cmd))
        self.status = "Thinking"
        self._start_new_turn(cmd)
        self._start_agent_stream(cmd)

    def _handle_command(self, cmd: str) -> None:
        c = cmd.lower()
        if c == "/new":
            self.thread_id = str(uuid.uuid4())
            self._invoke_config = {"configurable": {"thread_id": self.thread_id}}
            self._emit(SystemEvent(text=f"New session: {self.thread_id[:8]}...", level=SystemLevel.INFO))
            self._last_assistant_text = ""
            self._active_agent = self.agent
            self._post_system_welcome()
            return
        if c == "/config":
            self._post_config()
            return
        if c == "/init":
            # Project-memory refresh command; we use a heavier agent on purpose.
            init_prompt = self._build_init_prompt()
            self._emit(UserEvent(text="/init"))
            self._emit(SystemEvent(
                text=(
                    "Running /init: building/updating agents.md with comprehensive project understanding "
                    "(xhigh effort + reflection sub-agent review)."
                ),
                level=SystemLevel.INFO,
            ))
            self._start_new_turn("/init")
            self._start_agent_stream(init_prompt, agent_override=self._get_init_agent())
            return
        if c == "/help":
            self._emit(SystemEvent(text="Commands: /new /init /config /quit /help", level=SystemLevel.INFO))
            return

        self._emit(SystemEvent(text=f"Unknown command: {cmd}", level=SystemLevel.WARNING))

    def _get_init_agent(self) -> Any:
        if self._init_agent is not None:
            return self._init_agent

        from ..agent import create_agent

        # Create a high-effort agent for /init
        init_config = AppConfig(
            azure=self.config.azure,
            agent=self.config.agent,
        )
        init_config.agent.reasoning_effort = "high"
        self._init_agent = create_agent(init_config, reasoning_effort_override="high")
        return self._init_agent

    def _build_init_prompt(self) -> str:
        root_dir = self.config.agent.root_dir
        return (
            "Execute the /init project bootstrap workflow now.\n\n"
            "Primary objective:\n"
            "Create a comprehensive end-to-end understanding of this project and save it in agents.md at the repository root.\n\n"
            "Mandatory requirements:\n"
            "1) Operate at xhigh reasoning depth (maximum thoroughness).\n"
            "2) If agents.md exists, read and ingest it first, then amend/upgrade it; preserve useful content and correct stale info.\n"
            "3) If agents.md does not exist, create it.\n"
            "4) Build understanding from actual project artifacts (source code, config, docs), not from assumptions.\n"
            "5) The resulting agents.md must cover architecture, entry points, runtime flow, configuration model, tools, commands, and dependencies.\n"
            "6) Include concrete file references where possible.\n"
            "7) After drafting agents.md, you MUST spin up a reflection sub-agent to review the output for accuracy.\n"
            "8) Apply the reflection findings by editing agents.md before finishing.\n"
            "9) Final response should summarize what changed in agents.md and what the reflection sub-agent validated/fixed.\n"
            f"Working directory for this session: {root_dir}\n"
        )

    # ----------------------------- Streaming worker -----------------------------

    def _start_new_turn(self, user_message: str) -> None:
        self._active_turn_id = self._interaction_logger.new_turn_id()
        self._active_turn_tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self._turn_seen_usage_keys.clear()
        self._interaction_logger.log_request(
            thread_id=self.thread_id,
            turn_id=self._active_turn_id,
            message=user_message,
        )
        self._interaction_logger.flush()

    def _finish_turn(self, *, status: str, error: str | None = None) -> None:
        if not self._active_turn_id:
            return

        tokens = self._active_turn_tokens
        normalized = {
            "input_tokens": tokens.get("input_tokens") or 0,
            "output_tokens": tokens.get("output_tokens") or 0,
            "total_tokens": tokens.get("total_tokens") or 0,
        }

        self._interaction_logger.log_completion(
            thread_id=self.thread_id,
            turn_id=self._active_turn_id,
            status=status,
            token_usage=normalized,
            error=error,
        )
        self._interaction_logger.flush(force=True)
        self._active_turn_id = None

    def _start_agent_stream(self, user_message: str, *, agent_override: Any | None = None) -> None:
        agent = agent_override or self._active_agent
        self.run_worker(
            self._stream_worker(agent, user_message),
            name="agent_stream",
            group="agent",
            exclusive=True,
        )

    async def _stream_worker(self, agent: Any, user_message: str) -> None:
        """Run the agent stream in a worker.

        We redirect stdout to avoid dependency spam (raw JSON traces).
        UI updates are posted back to the main thread via call_from_thread.
        """
        stdout_buf = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buf):
                stream = agent.stream(
                    {"messages": [{"role": "user", "content": user_message}]},
                    config=self._invoke_config,
                    stream_mode="updates",
                )

                for update in stream:
                    self._process_stream_updates([update])

            # After stream completes, check for pending interrupts.
            self._check_interrupts()

        except Exception as e:
            self._emit(SystemEvent(text=f"Error: {e}", level=SystemLevel.ERROR))
            self._finish_turn(status="error", error=str(e))
            self._set_idle()
        else:
            if not self._approval_pending:
                self._finish_turn(status="completed")
                self._set_idle()
        finally:
            _ = stdout_buf.getvalue()

    def _process_stream_updates(self, updates: list) -> None:
        """Process a batch of stream updates from the agent."""
        for event in updates:
            if not isinstance(event, dict):
                continue
            for node_name, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue
                messages = state_update.get("messages", [])
                for msg in messages:
                    self._render_message(msg)

    def _render_message(self, msg: Any) -> None:
        """Render a single message from the stream."""
        # Extract token usage if present
        usage = extract_token_usage(msg)
        if usage is not None:
            # Deduplicate: avoid double-counting if the same message is yielded twice
            msg_id = id(msg)
            key = f"{msg_id}"
            if key not in self._turn_seen_usage_keys:
                self._turn_seen_usage_keys.add(key)
                self._active_turn_tokens = merge_token_usage(self._active_turn_tokens, usage)

        # Show tool calls on AI messages
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                summary, details = summarize_tool_call(name, args)
                self._emit(ToolCallEvent(name=name, summary=summary, details=details))

        # Show message content
        content = getattr(msg, "content", None)
        if not content:
            return

        msg_type = getattr(msg, "type", None)
        if msg_type == "ai":
            text = str(content)
            if text.strip():
                self._last_assistant_text = text
                self._timeline_plain_lines.append(f"Assistant: {text}")
                self._emit(AssistantEvent(markdown=text))
        elif msg_type == "tool":
            tool_name = getattr(msg, "name", "tool")
            summary, details = summarize_tool_result(tool_name, content)
            self._emit(ToolResultEvent(name=tool_name, summary=summary, details=details))

    # ----------------------------- HITL interrupts -----------------------------

    def _check_interrupts(self) -> None:
        """Check for pending HITL interrupts and show approval UI if needed."""
        pending = find_pending_approval(self._active_agent, self._invoke_config)
        if pending is None:
            return

        self._approval_pending = True
        summary, details = approval_ui_text(pending.tool_name, pending.tool_args)
        approval_event = ApprovalRequestEvent(
            tool_name=pending.tool_name,
            summary=summary,
            details=details,
            request_count=pending.request_count,
        )
        self._emit(approval_event)
        self._pending_request_count = pending.request_count
        self.status = "Waiting approval"

        dock = self.query_one(ApprovalDock)
        dock.show_request(approval_event)

        # Disable input while approval pending
        self.query_one("#prompt", TextArea).disabled = True

    def on_button_pressed(self, event) -> None:
        if event.button.id == "approve":
            self._resume_after_approval(True)
        elif event.button.id == "reject":
            self._resume_after_approval(False)

    def _resume_after_approval(self, approved: bool) -> None:
        # Hide dock + re-enable input immediately
        self.query_one(ApprovalDock).clear()
        self._approval_pending = False

        if not approved:
            self._emit(SystemEvent(text="Action rejected.", level=SystemLevel.INFO))
            self._finish_turn(status="rejected")
            self._set_idle()
            return

        self.status = "Thinking"

        self.run_worker(
            self._resume_worker(approved, self._pending_request_count),
            name="agent_resume",
            group="agent",
            exclusive=True,
        )

    async def _resume_worker(self, approved: bool, request_count: int) -> None:
        """Resume the agent after a HITL approval.

        Note: Textual async workers run on the app's asyncio loop (same thread as
        the UI). Therefore we must *not* use call_from_thread here.
        """
        stdout_buf = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buf):
                try:
                    from langgraph.types import Command
                except ImportError as e:
                    self._emit(SystemEvent(
                        text=f"Cannot resume (missing langgraph Command): {e}",
                        level=SystemLevel.ERROR,
                    ))
                    self._finish_turn(status="error", error=str(e))
                    self._set_idle()
                    return

                payload = build_decisions(approved, request_count)
                stream = self._active_agent.stream(
                    Command(resume=payload),
                    config=self._invoke_config,
                    stream_mode="updates",
                )

                for update in stream:
                    self._process_stream_updates([update])

            # After resume completes, check if more interrupts exist.
            self._check_interrupts()

        except Exception as e:
            self._emit(SystemEvent(text=f"Error: {e}", level=SystemLevel.ERROR))
            self._finish_turn(status="error", error=str(e))
            self._set_idle()
        else:
            if not self._approval_pending:
                self._finish_turn(status="completed")
                self._set_idle()
        finally:
            _ = stdout_buf.getvalue()
