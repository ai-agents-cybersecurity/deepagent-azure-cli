"""Textual widgets for the DeepAgent TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Label, Markdown, Static

from .events import (
    ApprovalRequestEvent,
    AssistantEvent,
    SystemEvent,
    SystemLevel,
    ToolCallEvent,
    ToolResultEvent,
    UserEvent,
)


class Timeline(VerticalScroll):
    """Scrollable timeline of conversation events.

    Render each event as a single line to avoid the "blank bordered cards"
    symptom reported in some terminals.
    """

    DEFAULT_CSS = """
    Timeline {
        height: 1fr;
        border: round $surface;
    }

    .line {
        padding: 0 1;
    }

    .user { color: $success; }
    .assistant { color: $primary; }
    .tool { color: $warning; }
    .system { color: $secondary; }
    .system-warning { color: $warning; }
    .system-error { color: $error; }
    """

    def add_event(self, event) -> None:
        """Render immediately (no batching) so the UI feels chatty and responsive."""
        if isinstance(event, UserEvent):
            text = f"You: {event.text}".strip()
            self.mount(Static(text or "You:", classes="line user"))

        elif isinstance(event, AssistantEvent):
            # Show full assistant content (not just the first line), otherwise it
            # looks like the response body is missing.
            markdown = (event.markdown or "").strip()
            text = f"Assistant: {markdown}" if markdown else "Assistant:"
            self.mount(Static(text, classes="line assistant"))

        elif isinstance(event, ToolCallEvent):
            text = f"Tool: {event.name} - {event.summary}".strip()
            self.mount(Static(text, classes="line tool"))

        elif isinstance(event, ToolResultEvent):
            text = f"Result: {event.name} - {event.summary}".strip()
            self.mount(Static(text, classes="line tool"))

        elif isinstance(event, SystemEvent):
            cls = "line system"
            if event.level == SystemLevel.WARNING:
                cls = "line system-warning"
            elif event.level == SystemLevel.ERROR:
                cls = "line system-error"
            self.mount(Static(f"System: {event.text}", classes=cls))

        elif isinstance(event, ApprovalRequestEvent):
            text = f"Approval needed: {event.tool_name} - {event.summary}"
            self.mount(Static(text, classes="line system-warning"))

        self.scroll_end(animate=False)


class ApprovalDock(Container):
    """Approve/Reject UI shown when HITL interrupt is pending."""

    DEFAULT_CSS = """
    ApprovalDock {
        height: auto;
        border: round $warning;
        padding: 1 2;
        margin: 1 1 1 1;
        background: $panel;
    }

    ApprovalDock .buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }

    ApprovalDock Button {
        margin-right: 1;
        min-width: 14;
        height: 3;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._current: ApprovalRequestEvent | None = None

    def compose(self) -> ComposeResult:
        yield Label("Approval required", classes="title")
        yield Static("", id="approval_summary")
        yield Static("", id="approval_details")
        with Container(classes="buttons"):
            yield Button("Approve", id="approve", variant="success")
            yield Button("Reject", id="reject", variant="error")

    def show_request(self, event: ApprovalRequestEvent) -> None:
        """Show an approval request in the dock."""
        self._current = event
        self.query_one("#approval_summary", Static).update(event.summary)
        self.query_one("#approval_details", Static).update(event.details or "")
        self.display = True

    def clear(self) -> None:
        """Hide the dock and clear the current request."""
        self._current = None
        self.display = False

    @property
    def current(self) -> ApprovalRequestEvent | None:
        return self._current
