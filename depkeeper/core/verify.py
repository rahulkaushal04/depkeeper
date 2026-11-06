"""Verify that a set of requirement strings can be installed together.

Runs ``pip install --dry-run --ignore-installed --only-binary=:all: --report``
(pip >= 22.2) so the full dependency resolver runs but nothing is installed.
Never raises: environmental problems (old/missing pip, no network, timeout)
yield ``skipped=True``.

Safety: ``--only-binary=:all:`` means pip never builds a source distribution,
so no ``setup.py``/PEP 517 hook of a freshly published release is executed.
Consequence: a requirement that has no wheel (sdist-only, or a nonexistent
version) fails with "No matching distribution found"; that is reported as a
failure (``ok=False``, not skipped) with a message naming this possibility.

Environment: pip's own configuration (``PIP_INDEX_URL``,
``PIP_EXTRA_INDEX_URL``, ``PIP_CONSTRAINT``, credentials, ...) is kept so
private indexes keep working and are not silently replaced by public PyPI.
Only variables that would change what is being resolved or where it is
installed are removed (see ``_STRIP_ENV``). Output is passed through
`redact` so URL credentials never reach the user.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_MIN_PIP = (22, 2)
_CRED_RE = re.compile(r"(://)[^/\s:@]+(?::\S*)?@")
#: pip env vars that would defeat a dry-run resolution of our plan.
_STRIP_ENV = frozenset(
    {
        "PIP_REQUIRE_VIRTUALENV",
        "PIP_USER",
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_ROOT",
        "PIP_REQUIRE_HASHES",
        "PIP_NO_DEPS",
        "PIP_REQUIREMENT",
        "PIP_NO_BINARY",
        "PIP_PRE",
        "PIP_DRY_RUN",
        "PIP_REPORT",
        "PIP_IGNORE_INSTALLED",
    }
)
_NET_RE = re.compile(
    r"(Failed to establish a new connection|Temporary failure in name resolution|"
    r"Could not fetch URL|Connection (?:timed out|refused|reset)|"
    r"ProxyError|SSLError|Max retries exceeded)",
    re.I,
)
_CONFLICT_RE = re.compile(r"Cannot install (.+?) because these package versions", re.S)
_DETAIL_RE = re.compile(r"^\s+(\S.*?)\s+depends on\s+(.+?)\s*$")
_VER_RE = re.compile(r"pip (\d+)\.(\d+)")


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a dry-run verification.

    ``skipped`` means verification could not run (``ok`` is then ``False``).
    """

    ok: bool
    skipped: bool
    message: str
    conflicts: List[str]


def redact(text: str) -> str:
    """Hide ``user:pass@`` credentials embedded in URLs."""
    return _CRED_RE.sub(r"\1***@", text)


def _run(args: List[str], timeout: float) -> Tuple[int, str, str]:
    """Run *args* and return ``(returncode, stdout, stderr)``; tests mock this."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in _STRIP_ENV}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    p = subprocess.run(  # noqa: S603 -- list args, no shell
        args, capture_output=True, text=True, timeout=timeout, env=env, check=False
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def parse_conflicts(output: str) -> List[str]:
    """Extract concise conflict lines from pip's failure output."""
    lines: List[str] = []
    for m in _CONFLICT_RE.finditer(output):
        lines.append("Cannot install " + " ".join(m.group(1).split()))
    for raw in output.splitlines():
        d = _DETAIL_RE.match(raw)
        if d:
            lines.append(f"{d.group(1)} depends on {d.group(2)}")
    if not lines and "ResolutionImpossible" in output:
        lines.append("pip reported ResolutionImpossible")
    return [redact(x) for x in dict.fromkeys(lines)]


def verify_plan(
    requirements: Sequence[str],
    *,
    python_executable: Optional[str] = None,
    timeout: float = 120.0,
    constraints: Sequence[str] = (),
) -> VerifyResult:
    """Ask pip's resolver whether *requirements* are mutually installable.

    Args:
        requirements: Requirement lines to resolve together.
        python_executable: Interpreter whose pip is used. Defaults to the
            running interpreter.
        timeout: Seconds before the resolution is abandoned.
        constraints: Constraint lines (e.g. ``-c`` entries), passed via a
            temporary constraints file.

    Returns:
        A `VerifyResult`; never raises.
    """

    def skip(msg: str) -> VerifyResult:
        return VerifyResult(False, True, redact(msg), [])

    py = python_executable or sys.executable
    path = report = cpath = ""
    try:
        try:
            code, out, err = _run([py, "-m", "pip", "--version"], 30.0)
        except (OSError, subprocess.SubprocessError) as e:
            return skip(f"pip unavailable: {e}")
        m = _VER_RE.search(out)
        if code != 0 or not m:
            return skip("pip is not available; skipping verification")
        if (int(m.group(1)), int(m.group(2))) < _MIN_PIP:
            return skip("pip >= 22.2 is required for --dry-run verification")

        fd, path = tempfile.mkstemp(suffix=".txt", prefix="depkeeper-req-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:  # mkstemp is 0600
            fh.write("\n".join(requirements) + "\n")
        fd, report = tempfile.mkstemp(suffix=".json", prefix="depkeeper-rep-")
        os.close(fd)

        args = [
            py,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--only-binary=:all:",
            "--quiet",
            "--report",
            report,
            "-r",
            path,
        ]
        if constraints:
            fd, cpath = tempfile.mkstemp(suffix=".txt", prefix="depkeeper-con-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(constraints) + "\n")
            args += ["-c", cpath]
        try:
            code, out, err = _run(args, timeout)
        except subprocess.TimeoutExpired:
            return skip(f"pip resolution timed out after {timeout:g}s")
        except (OSError, subprocess.SubprocessError) as e:
            return skip(f"could not run pip: {e}")

        if code == 0:
            return VerifyResult(True, False, "All requirements resolve together", [])
        text = out + "\n" + err

        # pip names our temp file; show the requirement it stands for instead.
        def _line(m: "re.Match[str]") -> str:
            n = int(m.group(1))
            return requirements[n - 1] if 0 < n <= len(requirements) else m.group(0)

        conflicts = [
            re.sub(r"-r \S+ \(line (\d+)\)", _line, c) for c in parse_conflicts(text)
        ]
        if conflicts:
            return VerifyResult(
                False, False, "Conflicting dependencies found", conflicts
            )
        if _NET_RE.search(text):
            return skip("network unreachable or package index unavailable")
        tail = (
            redact(text.strip().splitlines()[-1]) if text.strip() else "unknown error"
        )
        if "No matching distribution found" in text:
            return VerifyResult(
                False,
                False,
                "pip found no installable binary distribution (version does not "
                "exist, unsupported Python, or source-only; source distributions "
                f"are never built during verification): {tail}",
                [],
            )
        return VerifyResult(False, False, f"pip failed: {tail}", [])
    except Exception as e:  # noqa: BLE001 -- contract: never raise
        return skip(f"verification failed unexpectedly: {e}")
    finally:
        for f in (path, report, cpath):
            if f:
                try:
                    os.unlink(f)
                except OSError:
                    pass
