"""Suite-wide fixtures and test isolation guards.

Everything here is either shared by more than one package of tests or exists to
stop one test from changing process-global state another test depends on.
Module-specific helpers belong in the module that uses them.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Iterator, List

import pytest

from depkeeper.utils import console as console_module
from tests.support.factories import make_conflict, make_package, make_requirement


# ---------------------------------------------------------------------------
# Process-global state guards
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_depkeeper_logger() -> Iterator[None]:
    """Restore the ``depkeeper`` logger's configuration after every test.

    ``setup_logging`` — reached by any test that invokes the CLI through
    ``CliRunner``, and directly by the logger tests — clears the handlers and
    sets ``propagate = False`` on the shared ``depkeeper`` logger. That is
    correct for a CLI process but leaks across tests: once propagation is off,
    ``caplog`` silently captures nothing in every module that runs afterwards,
    so assertions on log output pass in isolation and fail in the full suite.

    Snapshotting here makes log-based assertions order-independent.
    """
    logger = logging.getLogger("depkeeper")
    handlers = list(logger.handlers)
    level = logger.level
    propagate = logger.propagate
    disabled = logger.disabled

    try:
        yield
    finally:
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled


@pytest.fixture(autouse=True)
def _isolate_console() -> Iterator[None]:
    """Drop the memoised Rich consoles around every test.

    ``depkeeper.utils.console`` caches one :class:`~rich.console.Console` per
    stream, capturing the colour decision made the first time it is used. A
    test that sets ``NO_COLOR`` or patches ``isatty`` would otherwise pin that
    decision for the rest of the session.
    """
    console_module.reconfigure_console()
    try:
        yield
    finally:
        console_module.reconfigure_console()


@pytest.fixture(autouse=True)
def _isolate_event_loop_policy() -> Iterator[None]:
    """Restore a usable event loop after ``asyncio.run()`` clears it.

    ``CliRunner``-driven tests call ``asyncio.run()`` (via the ``check``/
    ``update`` commands), which unsets the main thread's current loop. On
    Python < 3.10, building an ``asyncio.Lock``/``Semaphore`` outside a
    running loop (as ``HTTPClient``/``PyPIDataStore`` do in ``__init__``)
    needs that loop and raises once it's been unset, breaking any later test
    that constructs those objects directly.
    """
    yield
    try:
        loop = asyncio.get_event_loop()
        closed = loop.is_closed()
    except RuntimeError:
        closed = True
    if closed:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force colourless Rich output so assertions can match plain text."""
    monkeypatch.setenv("NO_COLOR", "1")
    console_module.reconfigure_console()


@pytest.fixture
def instant_sleep(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Make ``asyncio.sleep`` return immediately and record its durations.

    Retry and rate-limit code paths are defined by *how long* they wait, but
    actually waiting makes the suite slow and turns every assertion into a
    wall-clock race. Recording the requested delays instead lets tests assert
    on the backoff schedule exactly, and deterministically.

    Returns:
        The list that receives each requested delay, in call order.
    """
    delays: List[float] = []
    real_sleep = asyncio.sleep

    async def _record(delay: float, *args: object, **kwargs: object) -> None:
        delays.append(delay)
        # Yield to the loop so concurrency-sensitive code still interleaves.
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return delays


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------
# Exposed as fixtures as well as importable functions so that parameterised
# cases can build objects at collection time while plain tests stay terse.


@pytest.fixture
def requirement() -> Callable[..., object]:
    """Return :func:`tests.support.factories.make_requirement`."""
    return make_requirement


@pytest.fixture
def package() -> Callable[..., object]:
    """Return :func:`tests.support.factories.make_package`."""
    return make_package


@pytest.fixture
def conflict() -> Callable[..., object]:
    """Return :func:`tests.support.factories.make_conflict`."""
    return make_conflict


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def requirements_file(tmp_path: Path) -> Callable[[str], Path]:
    """Return a helper that writes ``requirements.txt`` into ``tmp_path``.

    Returns:
        ``write(content, name="requirements.txt") -> Path``. Content is written
        as UTF-8 without a BOM and without newline translation, so tests that
        assert on exact bytes stay meaningful on Windows.
    """

    def _write(content: str, name: str = "requirements.txt") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return path

    return _write
