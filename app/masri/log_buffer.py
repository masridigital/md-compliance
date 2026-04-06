"""
In-memory + Redis ring buffer for capturing application logs.

Used by the system page real-time log viewer. Stores the last N log
entries in memory — and optionally in Redis for cross-worker visibility
and persistence across restarts.

Usage in __init__.py::

    from app.masri.log_buffer import BufferHandler, get_recent_logs
    handler = BufferHandler(capacity=500, redis_url="redis://redis:6379/0")
    app.logger.addHandler(handler)
"""

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime

_lock = threading.Lock()
_buffer = deque(maxlen=500)
_redis_client = None
_worker_id = str(os.getpid())

_REDIS_KEY = "masri:logs"
_REDIS_MAX = 500


class BufferHandler(logging.Handler):
    """Logging handler that stores formatted records in a ring buffer.

    Supports optional Redis backend for cross-worker log aggregation.
    Falls back to in-memory deque if Redis is unavailable.
    """

    def __init__(self, capacity=500, redis_url=None):
        super().__init__()
        global _buffer, _redis_client
        _buffer = deque(maxlen=capacity)

        if redis_url:
            try:
                import redis as _redis_mod
                client = _redis_mod.from_url(redis_url, decode_responses=True)
                client.ping()
                _redis_client = client
            except Exception:
                _redis_client = None  # Fallback to in-memory only

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
                "worker": _worker_id,
            }
            if record.exc_info and record.exc_info[1]:
                import traceback
                tb = "".join(traceback.format_exception(*record.exc_info))
                entry["traceback"] = self._redact(tb)

            # Always write to in-memory buffer (fast, no-fail)
            with _lock:
                _buffer.append(entry)

            # Also push to Redis if available
            if _redis_client is not None:
                try:
                    _redis_client.lpush(_REDIS_KEY, json.dumps(entry))
                    _redis_client.ltrim(_REDIS_KEY, 0, _REDIS_MAX - 1)
                except Exception:
                    pass  # Redis down — in-memory still works
        except Exception:
            pass


def get_recent_logs(limit=200, level=None, since=None):
    """Return recent log entries from Redis (preferred) or in-memory buffer.

    Args:
        limit: Max entries to return
        level: Filter by level (ERROR, WARNING, etc.)
        since: ISO timestamp — only return entries after this time

    Returns:
        list of log entry dicts
    """
    entries = None

    # Try Redis first (cross-worker, persistent)
    if _redis_client is not None:
        try:
            raw = _redis_client.lrange(_REDIS_KEY, 0, _REDIS_MAX - 1)
            entries = [json.loads(r) for r in raw]
        except Exception:
            entries = None  # Fall through to in-memory

    # Fallback to in-memory buffer
    if entries is None:
        with _lock:
            entries = list(_buffer)

    if level:
        level_upper = level.upper()
        entries = [e for e in entries if e["level"] == level_upper]

    if since:
        entries = [e for e in entries if e["ts"] > since]

    return entries[-limit:]
