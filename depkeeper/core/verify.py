"""Verify that a set of requirement strings can be installed together.

Runs ``pip install --dry-run --ignore-installed --only-binary=:all: --report``
(pip >= 22.2) so the full dependency resolver runs but nothing is installed.
Never raises: environmental problems (old/missing pip, no network, timeout)
yield ``skipped=True``.

Target Python: when the target differs from the interpreter running pip,
``--python-version X.Y`` is passed so wheel selection and ``Requires-Python``
filtering follow the target. pip only accepts that flag together with
``--dry-run`` from 23.3 (earlier versions demand ``--target``); with an older
pip and a different target the check is skipped with a precise message.

Safety: ``--only-binary=:all:`` means pip never builds a source distribution,
so no ``setup.py``/PEP 517 hook of a freshly published release is executed.
A "No matching distribution found" is then classified: the version does not
exist or is Python-incompatible (failure), or it exists on the index but only
as a source distribution (``skipped=True``: depkeeper cannot judge it without
building it).

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
import json
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from depkeeper.utils.redact import redact

_MIN_PIP = (22, 2)
#: First pip that accepts ``--python-version`` together with ``--dry-run``.
_MIN_PIP_TARGET = (23, 3)
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
_VER_RE = re.compile(r"pip ([0-9]+)\.([0-9]+)(?:\.[0-9]+)?")
_PIP_PY_RE = re.compile(r"\(python ([0-9]+\.[0-9]+)\)")
_PY_RE = re.compile(r"\A\s*([0-9]+)\.([0-9]+)(?:\.[0-9]+)*\s*\Z")
_NO_DIST_RE = re.compile(r"No matching distribution found for (\S+)")
_AVAILABLE_RE = re.compile(r"Available versions:\s*(.+)")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_IGNORED_RE = re.compile(r"(\S+) Requires-Python")


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a dry-run verification.

    ``skipped`` means verification could not run or could not be judged
    (``ok`` is then ``False``). The trailing fields describe what a successful
    run verified; they default to empty so older constructions stay valid.

    Attributes:
        ok: Whether pip resolved the set.
        skipped: Whether the check could not run or be judged.
        message: Human-readable outcome.
        conflicts: Concise conflict lines when ``ok`` is ``False``.
        pip_version: ``major.minor`` of the pip that resolved.
        python_version: ``X.Y`` the set was resolved for.
        platform: Platform pip resolved for (from its report), e.g.
            ``linux-x86_64``; empty when pip did not say.
        checked: Number of distributions in pip's resolved install set.
        constraints: Number of ``-c`` constraint lines applied.
        not_applicable: Requirements dropped because their environment marker
            is false for the target Python.
    """

    ok: bool
    skipped: bool
    message: str
    conflicts: List[str]
    pip_version: str = ""
    python_version: str = ""
    platform: str = ""
    checked: int = 0
    constraints: int = 0
    not_applicable: int = 0

    def summary(self, constraints: Optional[int] = None, excluded: int = 0) -> str:
        """One line stating exactly what was verified.

        Args:
            constraints: Override for the constraint count shown.
            excluded: Direct URL/editable requirements left out of the check.

        Returns:
            For example ``pip 24.0 resolved 14 requirements for Python 3.9
            (linux-x86_64); 2 constraints applied``.
        """
        if not self.pip_version:
            return "pip resolved the proposed set"
        n = self.checked
        text = f"pip {self.pip_version} resolved {n} requirement{'s' * (n != 1)}"
        if self.python_version:
            text += f" for Python {self.python_version}"
        if self.platform:
            text += f" ({self.platform})"
        c = self.constraints if constraints is None else constraints
        if c:
            text += f"; {c} constraint{'s' * (c != 1)} applied"
        if self.not_applicable:
            text += f"; {self.not_applicable} skipped by markers"
        if excluded:
            text += (
                f"; {excluded} direct URL/editable requirement"
                f"{'s' * (excluded != 1)} not checked"
            )
        return text


def _kill_tree(p: "subprocess.Popen[str]") -> None:
    """Kill *p* and everything it spawned (pip may fork build helpers)."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603, S607 -- fixed argv
            ["taskkill", "/F", "/T", "/PID", str(p.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)  # session leader: pgid == pid
        except OSError:
            pass
    p.kill()


def _run(args: List[str], timeout: float) -> Tuple[int, str, str]:
    """Run *args* and return ``(returncode, stdout, stderr)``; tests mock this.

    On timeout or interruption (``KeyboardInterrupt``/``SystemExit``) the
    whole process tree is killed before the exception propagates.
    """
    env = {k: v for k, v in os.environ.items() if k.upper() not in _STRIP_ENV}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    kw: Dict[str, Any] = {} if sys.platform == "win32" else {"start_new_session": True}
    with subprocess.Popen(  # noqa: S603 -- list args, no shell
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        **kw,
    ) as p:
        try:
            out, err = p.communicate(timeout=timeout)
        except BaseException:  # timeout or Ctrl-C: never orphan pip
            _kill_tree(p)
            p.communicate()
            raise
    return p.returncode, out or "", err or ""


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


def _index_versions(
    py: str, name: str, flag: Sequence[str] = ()
) -> Optional[List[str]]:
    """Versions of *name* the index lists, or ``None`` if unknown.

    Without *flag* the list is not filtered by the target Python, so a
    release that only needs a newer Python is not mistaken for a missing one.
    """
    try:
        code, out, _ = _run([py, "-m", "pip", "index", "versions", name, *flag], 30.0)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _AVAILABLE_RE.search(out)
    if code != 0 or not m:
        return None
    return [v.strip() for v in m.group(1).split(",") if v.strip()]


def _satisfying(versions: List[str], spec: SpecifierSet) -> List[str]:
    """Entries of *versions* accepted by *spec* (unparseable ones ignored)."""
    out: List[str] = []
    for v in versions:
        try:
            if spec.contains(Version(v), prereleases=True):
                out.append(v)
        except InvalidVersion:
            pass
    return out


def _no_distribution(
    text: str, tail: str, py: str, flag: List[str], target: str
) -> VerifyResult:
    """Classify "No matching distribution found" under ``--only-binary``.

    The offending package is parsed from pip's message (it may be a transitive
    dependency or carry a range). It is then compared with the index listing:
    no listed release satisfies it (missing: failure), the satisfying
    releases are all ones the target Python rules out (``Requires-Python``:
    failure), or some satisfying release exists but has no wheel (source-only:
    skipped, depkeeper never builds it).
    """
    m = _NO_DIST_RE.search(text)
    raw = m.group(1) if m else ""
    try:
        req = Requirement(raw)
        name, spec = req.name, req.specifier
    except InvalidRequirement:
        nm = _NAME_RE.match(raw)
        name, spec = (nm.group(0) if nm else ""), SpecifierSet()
    shown = f"{name}{spec}" if name else raw
    where = f" for Python {target}" if target else ""
    versions = _index_versions(py, name) if name else None
    if versions:
        found = _satisfying(versions, spec)
        if not found:
            return VerifyResult(
                False,
                False,
                f"{shown} does not exist on the package index (known versions: "
                f"{', '.join(versions[:5])}{', ...' if len(versions) > 5 else ''})",
                [],
            )
        blocked = set(_IGNORED_RE.findall(text))
        if flag and not all(v in blocked for v in found):
            # pip stays silent about Requires-Python under --python-version:
            # a release the target-filtered listing hides needs a newer Python.
            fit = _index_versions(py, name, flag)
            if fit is not None:
                blocked |= set(found) - set(fit)
        if all(v in blocked for v in found):
            return VerifyResult(
                False,
                False,
                f"{shown} exists on the index but no matching release supports "
                f"Python {target or 'the target'} (Requires-Python): {tail}",
                [],
            )
        return VerifyResult(
            False,
            True,
            f"cannot verify {shown} without building it: the index has no "
            f"installable wheel{where}, and source distributions are "
            "never built during verification",
            [],
        )
    if "require a different python version" in text:
        return VerifyResult(
            False,
            False,
            f"a requested release does not support Python {target or 'the target'}"
            f" (Requires-Python): {tail}",
            [],
        )
    return VerifyResult(
        False,
        False,
        "pip found no installable binary distribution (version does not "
        "exist, unsupported Python, or source-only; source distributions "
        f"are never built during verification): {tail}",
        [],
    )


def _applicable(requirements: Sequence[str], target: str) -> Tuple[List[str], int]:
    """Drop lines whose marker is false for *target*; strip the true markers.

    pip evaluates markers on the interpreter running it, so the decision is
    made here and a kept line is handed over without its (now settled) marker.
    Transitive markers still follow the host. Lines that do not parse as a
    plain requirement (options, hashes, ...) are kept untouched.

    Returns:
        ``(lines to resolve, number dropped)``.
    """
    env: Dict[str, Any] = dict(default_environment())
    if target:
        env.update(python_version=target, python_full_version=f"{target}.0")
    kept: List[str] = []
    for line in requirements:
        try:
            req = Requirement(line)
        except InvalidRequirement:
            kept.append(line)
            continue
        if req.marker is None:
            kept.append(line)
        elif req.marker.evaluate({**env, "extra": ""}):
            req.marker = None
            kept.append(str(req))
    return kept, len(requirements) - len(kept)


def verify_plan(
    requirements: Sequence[str],
    *,
    python_executable: Optional[str] = None,
    timeout: float = 120.0,
    constraints: Sequence[str] = (),
    python_version: Optional[str] = None,
) -> VerifyResult:
    """Ask pip's resolver whether *requirements* are mutually installable.

    Args:
        requirements: Requirement lines to resolve together.
        python_executable: Interpreter whose pip is used. Defaults to the
            running interpreter.
        timeout: Seconds before the resolution is abandoned; the whole pip
            process tree is killed.
        constraints: Constraint lines (e.g. ``-c`` entries), passed via a
            temporary constraints file.
        python_version: Target Python (``X.Y`` or longer) to resolve for.
            ``None`` means the interpreter running pip.

    Returns:
        A `VerifyResult`; never raises.
    """

    def skip(msg: str) -> VerifyResult:
        return VerifyResult(False, True, redact(msg), [])

    for line in (*requirements, *constraints):
        # Each line must be a plain PEP 508 requirement: pip reads the file as
        # a requirements file, where options (--index-url, -r, -e) are commands.
        try:
            if not line.strip() or len(line.splitlines()) != 1:
                raise InvalidRequirement("empty or multi-line")
            Requirement(line)
        except InvalidRequirement:
            return skip(f"cannot verify: not a plain requirement: {line[:80]!r}")

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
        pip_ver = (int(m.group(1)), int(m.group(2)))
        if pip_ver < _MIN_PIP:
            return skip("pip >= 22.2 is required for --dry-run verification")
        pip_text = f"{pip_ver[0]}.{pip_ver[1]}"
        pm = _PIP_PY_RE.search(out)
        host_py = pm.group(1) if pm else ""

        target = host_py
        flag: List[str] = []
        if python_version:
            tm = _PY_RE.match(python_version)
            if not tm:
                return skip(f"cannot interpret target Python {python_version!r}")
            target = f"{tm.group(1)}.{tm.group(2)}"
            if target != host_py:
                if pip_ver < _MIN_PIP_TARGET:
                    return skip(
                        f"pip >= 23.3 is required to verify for Python {target} "
                        f"from Python {host_py or 'another version'} "
                        f"(found pip {pip_text}); upgrade pip or run with "
                        f"Python {target}"
                    )
                flag = ["--python-version", target]

        requirements, dropped = _applicable(requirements, target)
        if dropped and not requirements:
            return skip(
                f"nothing to verify: all {dropped} requirement"
                f"{'s' * (dropped != 1)} are not applicable to Python {target}"
            )
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
            *flag,
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
            checked, plat = len(requirements), ""
            try:
                with open(report, encoding="utf-8") as fh:
                    data = json.load(fh)
                checked = len(data["install"])
                env = data.get("environment") or {}
                if env.get("sys_platform") and env.get("platform_machine"):
                    plat = f"{env['sys_platform']}-{env['platform_machine']}"
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
            return VerifyResult(
                True,
                False,
                "All requirements resolve together",
                [],
                pip_text,
                target,
                plat,
                checked,
                len(constraints),
                dropped,
            )
        text = out + "\n" + err

        # pip names our temp file; show the requirement it stands for instead.
        def _line(m: "re.Match[str]") -> str:
            n = int(m.group(1))
            return requirements[n - 1] if 0 < n <= len(requirements) else m.group(0)

        conflicts = [
            re.sub(r"-r \S+ \(line ([0-9]+)\)", _line, c) for c in parse_conflicts(text)
        ]
        if conflicts:
            return VerifyResult(
                False, False, "Conflicting dependencies found", conflicts
            )
        if _NET_RE.search(text):
            return skip("network unreachable or package index unavailable")
        if flag and re.search(
            r"platform or abi specific options|no such option: --python-version", text
        ):
            return skip(
                f"this pip does not support verifying for Python {target} "
                "(--python-version rejected with --dry-run)"
            )
        tail = (
            redact(text.strip().splitlines()[-1]) if text.strip() else "unknown error"
        )
        if "No matching distribution found" in text:
            res = _no_distribution(text, tail, py, flag, target)
            return VerifyResult(res.ok, res.skipped, redact(res.message), [])
        if re.search(r"^(?:Traceback \(most recent|\w+Error:)", text, re.M):
            return skip(f"pip crashed (unsupported on this interpreter?): {tail}")
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
