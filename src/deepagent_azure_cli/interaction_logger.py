"""Append-only JSONL interaction logger with daily file rotation.

Logs requests, completions, and token usage to ~/.deepagent-azure/logs/.
One file per day keeps log rotation dead simple and grep-friendly.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class DailyInteractionLogger:
    """Append-only JSONL logger with one file per day and periodic flushing."""

    def __init__(
        self,
        log_dir: str | Path | None = None,
        *,
        flush_interval_seconds: float = 10.0,
    ) -> None:
        base_dir = Path(log_dir) if log_dir else (Path.home() / ".deepagent-azure" / "logs")
        self._log_dir = base_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._flush_interval_seconds = flush_interval_seconds
        self._last_flush = time.monotonic()
        self._buffer: list[dict[str, Any]] = []

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat()

    @staticmethod
    def _day_from_timestamp(ts: str) -> str:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d")

    def _append(self, record: dict[str, Any]) -> None:
        self._buffer.append(record)

    def new_turn_id(self) -> str:
        return str(uuid.uuid4())

    def log_request(self, *, thread_id: str, turn_id: str, message: str) -> None:
        ts = self._now_iso()
        self._append(
            {
                "timestamp": ts,
                "event": "request",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "message": message,
                "tokens": None,
            }
        )

    def log_completion(
        self,
        *,
        thread_id: str,
        turn_id: str,
        status: str,
        token_usage: dict[str, int | None] | None = None,
        error: str | None = None,
    ) -> None:
        ts = self._now_iso()
        self._append(
            {
                "timestamp": ts,
                "event": "completion",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "status": status,
                "tokens": token_usage,
                "error": error,
            }
        )

    def flush(self, *, force: bool = False) -> None:
        """Write buffered records to disk.

        By default only flushes when the interval has elapsed, unless force=True.
        """
        if not self._buffer:
            return

        now = time.monotonic()
        if not force and (now - self._last_flush) < self._flush_interval_seconds:
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        for rec in self._buffer:
            day = self._day_from_timestamp(rec["timestamp"])
            grouped.setdefault(day, []).append(rec)

        for day, records in grouped.items():
            file_path = self._log_dir / f"deepagent-{day}.jsonl"
            with file_path.open("a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._buffer.clear()
        self._last_flush = now


def extract_token_usage(msg: Any) -> dict[str, int | None] | None:
    """Extract token usage from common LangChain/LLM message metadata shapes."""

    usage_md = getattr(msg, "usage_metadata", None)
    if isinstance(usage_md, dict):
        in_t = usage_md.get("input_tokens")
        out_t = usage_md.get("output_tokens")
        total_t = usage_md.get("total_tokens")
        if any(v is not None for v in (in_t, out_t, total_t)):
            return {
                "input_tokens": _coerce_int(in_t),
                "output_tokens": _coerce_int(out_t),
                "total_tokens": _coerce_int(total_t),
            }

    response_md = getattr(msg, "response_metadata", None)
    if isinstance(response_md, dict):
        token_usage = response_md.get("token_usage")
        if isinstance(token_usage, dict):
            in_t = token_usage.get("prompt_tokens")
            out_t = token_usage.get("completion_tokens")
            total_t = token_usage.get("total_tokens")
            if any(v is not None for v in (in_t, out_t, total_t)):
                return {
                    "input_tokens": _coerce_int(in_t),
                    "output_tokens": _coerce_int(out_t),
                    "total_tokens": _coerce_int(total_t),
                }

    return None


def merge_token_usage(
    total: dict[str, int | None],
    increment: dict[str, int | None],
) -> dict[str, int | None]:
    """Return a new usage dict with token counts added where available."""

    merged: dict[str, int | None] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        a = total.get(key)
        b = increment.get(key)
        if a is None and b is None:
            merged[key] = None
        else:
            merged[key] = (a or 0) + (b or 0)
    return merged


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None
