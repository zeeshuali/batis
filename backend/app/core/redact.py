"""Keep API keys out of logs.

`requests` embeds the full URL (including ``?api_key=...``) in HTTPError text,
and many loaders print exceptions. Rather than patching every print site,
worker entry points call ``install_redaction()`` once so anything written to
stdout/stderr or through ``logging`` is scrubbed.
"""
from __future__ import annotations

import logging
import re
import sys

_PATTERN = re.compile(r"(api_key|apikey|token)=[^&\s'\"]+", re.IGNORECASE)


def redact_secrets(msg: object) -> str:
    return _PATTERN.sub(lambda m: f"{m.group(1)}=***", str(msg))


class _RedactingStream:
    """File-like wrapper that scrubs text before it reaches the real stream."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        return self._stream.write(redact_secrets(data) if isinstance(data, str) else data)

    def __getattr__(self, name):  # flush, isatty, encoding, fileno, ...
        return getattr(self._stream, name)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def install_redaction() -> None:
    """Idempotent: safe to call from every worker entry point."""
    if not isinstance(sys.stdout, _RedactingStream):
        sys.stdout = _RedactingStream(sys.stdout)
    if not isinstance(sys.stderr, _RedactingStream):
        sys.stderr = _RedactingStream(sys.stderr)
    root = logging.getLogger()
    if not any(isinstance(f, _RedactingFilter) for f in root.filters):
        root.addFilter(_RedactingFilter())
        for h in root.handlers:
            h.addFilter(_RedactingFilter())
