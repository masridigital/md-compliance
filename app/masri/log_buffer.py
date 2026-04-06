"""
Ring buffer for capturing application logs, backed by Redis with
in-memory fallback.

Redis mode: LPUSH + LTRIM to a Redis LIST (key: ``md_compliance:logs``).
Fallback: in-memory deque (same as before) if Redis is unavailable.

Usage in __init__.py::

    from app.masri.log_buffer import BufferHandler, get_recent_logs
    handler = BufferHandler(capacity=500)
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

# Redis connection (lazy init)
_redis = None
_redis_checked = False
_REDIS_KEY = "md_compliance:logs"
_CAPACITY = 500


def _get_redis():
    """Lazy-init Redis connection. Returns None if unavailable."""
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        import redis
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
        _redis.ping()
    except Exception:
        _redis = None
    return _redis


def _get_worker_id():
    """Return a short worker identifier for multi-worker log attribution."""
    return f"w{os.getpid()}"


class BufferHandler(logging.Handler):
    """Logging handler that stores formatted records in Redis or memory."""

    def __init__(self, capacity=500):
        super().__init__()
        global _buffer, _CAPACITY
        _CAPACITY = capacity
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
                "worker": _get_worker_id(),
            }
            if record.exc_info and record.exc_info[1]:
                import traceback
                tb = "".join(traceback.format_exception(*record.exc_info))
                entry["traceback"] = self._redact(tb)

            # Try Redis first, fall back to in-memory
            r = _get_redis()
            if r:
                try:
                    r.lpush(_REDIS_KEY, json.dumps(entry))
                    r.ltrim(_REDIS_KEY, 0, _CAPACITY - 1)
                    return
                except Exception:
                    pass

            # Fallback: in-memory buffer
            with _lock:
                _buffer.append(entry)
        except Exception:
            pass


def get_recent_logs(limit=200, level=None, since=None):
    """Return recent log entries from Redis or the in-memory ring buffer.

    Args:
        limit: Max entries to return
        level: Filter by level (ERROR, WARNING, etc.)
        since: ISO timestamp — only return entries after this time

    Returns:
        list of log entry dicts (newest last)
    """
    entries = []

    # Try Redis first
    r = _get_redis()
    if r:
        try:
            raw = r.lrange(_REDIS_KEY, 0, _CAPACITY - 1)
            entries = []
            for item in reversed(raw):  # LPUSH stores newest first, we want oldest first
                try:
                    entries.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            entries = []

    # Fallback to in-memory if Redis returned nothing
    if not entries:
        with _lock:
            entries = list(_buffer)

    if level:
        level_upper = level.upper()
        entries = [e for e in entries if e["level"] == level_upper]

    if since:
        entries = [e for e in entries if e["ts"] > since]

    return entries[-limit:]
