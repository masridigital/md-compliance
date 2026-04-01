"""
In-memory ring buffer for capturing application logs.

Used by the system page real-time log viewer. Stores the last N log
entries in memory — no disk I/O, no DB writes, minimal overhead.

Usage in __init__.py::

    from app.masri.log_buffer import BufferHandler, get_recent_logs
    handler = BufferHandler(capacity=500)
    app.logger.addHandler(handler)
"""

import logging
import threading
from collections import deque
from datetime import datetime

_lock = threading.Lock()
_buffer = deque(maxlen=500)


class BufferHandler(logging.Handler):
    """Logging handler that stores formatted records in a ring buffer."""

    def __init__(self, capacity=500):
        super().__init__()
        global _buffer
        _buffer = deque(maxlen=capacity)

    # Patterns to redact from log messages shown in the UI
    _REDACT_PATTERNS = None

    @classmethod
    def _get_redact_patterns(cls):
        if cls._REDACT_PATTERNS is None:
            import re
            cls._REDACT_PATTERNS = [
                (re.compile(r'(sk-[a-zA-Z0-9]{20,})'), '[REDACTED_API_KEY]'),
                (re.compile(r'(Bearer\s+[a-zA-Z0-9._\-]+)'), 'Bearer [REDACTED]'),
                (re.compile(r'(api[_-]?key["\s:=]+)["\']?([a-zA-Z0-9_\-]{16,})', re.I), r'\1[REDACTED]'),
                (re.compile(r'(secret["\s:=]+)["\']?([a-zA-Z0-9_\-]{16,})', re.I), r'\1[REDACTED]'),
                (re.compile(r'(password["\s:=]+)["\']?([^\s"\']{8,})', re.I), r'\1[REDACTED]'),
                (re.compile(r'(eyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+)'), '[REDACTED_JWT]'),
            ]
        return cls._REDACT_PATTERNS

    @classmethod
    def _redact(cls, text):
        """Remove API keys, tokens, passwords from log text before storing."""
        if not text:
            return text
        for pattern, replacement in cls._get_redact_patterns():
            text = pattern.sub(replacement, text)
        return text

    def emit(self, record):
        try:
            msg = self._redact(self.format(record))
            entry = {
                "ts": datetime.utcfromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": msg,
                "logger": record.name,
                "module": record.module,
            }
            if record.exc_info and record.exc_info[1]:
                import traceback
                tb = "".join(traceback.format_exception(*record.exc_info))
                entry["traceback"] = self._redact(tb)
            with _lock:
                _buffer.append(entry)
        except Exception:
            pass


def get_recent_logs(limit=200, level=None, since=None):
    """Return recent log entries from the ring buffer.

    Args:
        limit: Max entries to return
        level: Filter by level (ERROR, WARNING, etc.)
        since: ISO timestamp — only return entries after this time

    Returns:
        list of log entry dicts
    """
    with _lock:
        entries = list(_buffer)

    if level:
        level_upper = level.upper()
        entries = [e for e in entries if e["level"] == level_upper]

    if since:
        entries = [e for e in entries if e["ts"] > since]

    return entries[-limit:]
