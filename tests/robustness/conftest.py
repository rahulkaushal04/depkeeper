"""Gate for live-PyPI tests: one clear skip reason, or a failure when forced."""

from __future__ import annotations

import os
import socket
from functools import lru_cache
from typing import Optional

import pytest

REQUIRE_ENV = "DEPKEEPER_REQUIRE_NETWORK"


@lru_cache(maxsize=1)
def _unreachable_reason() -> Optional[str]:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return None
    except OSError as exc:
        return "pypi.org:443 unreachable (%s: %s)" % (type(exc).__name__, exc)


@pytest.fixture(autouse=True)
def _network_gate(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("network") is None:
        return
    reason = _unreachable_reason()
    if reason is None:
        return
    if os.environ.get(REQUIRE_ENV, "") not in ("", "0"):
        pytest.fail("%s=1 but %s" % (REQUIRE_ENV, reason))
    pytest.skip("network test skipped: %s (set %s=1 to fail)" % (reason, REQUIRE_ENV))
