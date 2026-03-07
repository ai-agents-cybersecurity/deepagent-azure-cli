"""UI event types for the Textual TUI.

These events are *internal* to the TUI layer. They exist to decouple:
- LangGraph/LangChain message objects (which may contain tool payloads)
from
- what we render to the user (human-friendly, never raw JSON / Python literals).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SystemLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class UserEvent:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    markdown: str


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    name: str
    summary: str
    details: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    name: str
    summary: str
    details: str | None = None


@dataclass(frozen=True, slots=True)
class SystemEvent:
    text: str
    level: SystemLevel = SystemLevel.INFO


@dataclass(frozen=True, slots=True)
class ApprovalRequestEvent:
    tool_name: str
    summary: str
    details: str | None
    request_count: int
