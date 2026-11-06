"""Mask URL credentials in text that may reach users or logs."""

from __future__ import annotations

import re

_CRED_RE = re.compile(r"(://)[^/\s:@]+(?::\S*)?@")
#: Query-string values that commonly carry credentials.
_QUERY_SECRET_RE = re.compile(
    r"([?&][^=&\s]*(?:token|key|secret|passw|auth|sig|credential)[^=&\s]*=)[^&\s]+",
    re.I,
)

__all__ = ["redact"]


def redact(text: str) -> str:
    """Hide ``user[:pass]@`` URL credentials and token-like query values."""
    return _QUERY_SECRET_RE.sub(r"\1***", _CRED_RE.sub(r"\1***@", text))
