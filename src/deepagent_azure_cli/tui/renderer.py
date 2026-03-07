"""Human-friendly rendering helpers for the Textual TUI.

Hard requirement: never emit raw JSON dumps or Python-literal blocks.

This module provides:
- tool call summarization
- tool args formatting for approvals
- safe truncation utilities
"""

from __future__ import annotations

import re
from typing import Any

_MAX_INLINE = 160
_MAX_DETAILS = 1200


def _one_line(text: str) -> str:
    """Normalize spacing early so summaries don't jitter between renders."""
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, max_len: int) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)] + "\u2026"  # visible truncation marker


def safe_kv_lines(d: dict[str, Any], *, max_value: int = 200) -> str:
    """Format dict as key/value lines without JSON or Python repr blocks."""
    lines: list[str] = []
    for k in sorted(d.keys()):
        v = d.get(k)
        if v is None:
            continue
        if isinstance(v, (dict, list, tuple)):
            # Avoid raw structured dumps; show type + size only.
            if isinstance(v, dict):
                v_str = f"<dict {len(v)} keys>"
            else:
                v_str = f"<{type(v).__name__} {len(v)} items>"
        else:
            v_str = _one_line(str(v))
        v_str = truncate(v_str, max_value)
        lines.append(f"- {k}: {v_str}")
    return "\n".join(lines)


def summarize_tool_call(tool_name: str, tool_input: Any) -> tuple[str, str | None]:
    """Return (summary, details) for a tool call."""
    if isinstance(tool_input, dict):
        args = tool_input

        if tool_name in ("read_file", "write_file", "edit_file"):
            path = args.get("path") or args.get("file_path") or "?"
            content = args.get("content") or args.get("new_content") or ""
            n = len(str(content)) if content else 0
            return (f"{tool_name.replace('_', ' ')} {path} ({n} chars)", None)

        if tool_name in ("ls", "glob"):
            path = args.get("path") or "?"
            if tool_name == "glob":
                pat = args.get("pattern") or "?"
                return (f"glob {path} / {pat}", None)
            return (f"list {path}", None)

        if tool_name == "execute":
            cmd = args.get("command") or args.get("cmd") or ""
            cmd = truncate(_one_line(str(cmd)), _MAX_INLINE)
            return (f"run: {cmd}", None)

        # Unknown tool fallback: enough signal for humans without flooding the timeline.
        keys = list(args.keys())
        keys_preview = ", ".join(keys[:6]) + ("" if len(keys) <= 6 else ", \u2026")
        details = safe_kv_lines(args)
        details = truncate(details, _MAX_DETAILS) if details else None
        return (f"{tool_name} ({keys_preview})", details)

    # Non-dict args: avoid repr; show type only.
    return (f"{tool_name} (<{type(tool_input).__name__}>)", None)


def format_approval_details(tool_name: str, tool_args: dict[str, Any]) -> tuple[str, str | None]:
    """Return (summary, details) for approval UI."""
    summary, details = summarize_tool_call(tool_name, tool_args)

    if tool_name == "execute":
        cmd = tool_args.get("command") or tool_args.get("cmd") or ""
        cmd = str(cmd).rstrip()
        cmd = truncate(cmd, 800)
        return (summary, cmd)

    if tool_name in ("write_file", "edit_file"):
        path = tool_args.get("path") or tool_args.get("file_path") or "?"
        content = tool_args.get("content") or tool_args.get("new_content") or ""
        if isinstance(content, str):
            preview = truncate(content, 800)
        else:
            preview = truncate(_one_line(str(content)), 200)
        return (f"{tool_name.replace('_', ' ')} {path}", preview)

    if tool_name == "read_file":
        path = tool_args.get("path") or tool_args.get("file_path") or "?"
        off = tool_args.get("offset")
        lim = tool_args.get("limit")
        extra = []
        if off is not None:
            extra.append(f"offset={off}")
        if lim is not None:
            extra.append(f"limit={lim}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return (f"read {path}{suffix}", None)

    return (summary, details)


_JSONISH = re.compile(r"^\s*[\[{].*[\]}]\s*$", re.DOTALL)


def summarize_tool_result(tool_name: str, content: Any) -> tuple[str, str | None]:
    """Summarize tool result content without dumping raw JSON."""
    text = "" if content is None else str(content)
    text = text.strip("\n")

    if not text:
        return ("done", None)

    # If it looks like JSON, do NOT pretty print; just summarize size.
    if _JSONISH.match(text) and len(text) > 40:
        return (f"result received ({len(text)} chars)", None)

    # Multi-line: show line count + first few lines.
    if "\n" in text:
        lines = text.splitlines()
        preview = "\n".join(lines[:12])
        preview = truncate(preview, 800)
        return (f"{len(lines)} lines", preview)

    # Single line: truncate.
    return (truncate(_one_line(text), 200), None)
