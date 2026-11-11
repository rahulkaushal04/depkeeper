"""Mask credentials in text that may reach users, logs or exceptions.

This is the single implementation: the parser, adapters, HTTP client and
verifier all import `redact` from here.
"""

from __future__ import annotations

import re
from typing import Match

# ``scheme://user[:password]@``; the password may contain any non-space byte.
_USERINFO_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<user>[^/\s:@]*)(?P<pw>:\S*)?@"
)
#: Query/fragment/matrix parameters that commonly carry credentials.
_QUERY_SECRET_RE = re.compile(
    r"([?&;#][^=&;\s]*(?:token|key|secret|passw|pwd|auth|sig|credential|bearer)"
    r"[^=&;\s]*=)[^&;\s]+",
    re.I,
)


def _mask_userinfo(m: Match[str]) -> str:
    # ``ssh://git@host`` names an account, not a secret; with a password, or on
    # any other scheme (``https://<token>@host``), the user part is masked.
    if m.group("scheme").lower().rstrip(":/").endswith("ssh") and not m.group("pw"):
        return m.group(0)
    return m.group("scheme") + "***@"


def redact(text: str) -> str:
    """Hide URL credentials and token-like query values in *text*.

    Covers ``user:pass@`` and ``token@`` userinfo (also inside VCS URLs and
    ``--index-url`` / ``--extra-index-url`` / ``--find-links`` option lines),
    and values of ``token=``, ``access_token=``, ``key=``, ``password=``,
    ``x-access-token=`` style parameters. ``git+ssh://git@host`` keeps its
    account name; an unexpanded ``${TOKEN}`` placeholder is not a secret.
    """
    return _QUERY_SECRET_RE.sub(r"\1***", _USERINFO_RE.sub(_mask_userinfo, text))


__all__ = ["redact"]
