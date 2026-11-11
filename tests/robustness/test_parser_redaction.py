"""Credentials never survive in errors, details or logs from any parser or adapter path."""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources.conda_yaml import CondaYamlAdapter
from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter
from depkeeper.exceptions import DepKeeperError, NetworkError, ParseError
from depkeeper.utils.redact import redact

ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.~%"


def _secret(rng: random.Random) -> str:
    return "S3c" + "".join(rng.choice(ALPHABET) for _ in range(rng.randint(8, 24)))


REDACT_CASES = [
    ("https://user:{s}@host/x", "https://***@host/x"),
    ("https://{s}@host/x", "https://***@host/x"),
    ("git+https://user:{s}@github.com/o/r.git#egg=r", None),
    ("git+https://{s}@github.com/o/r.git", None),
    ("--index-url https://u:{s}@h/simple", None),
    ("--extra-index-url=https://{s}@h/simple", None),
    ("--find-links https://u:{s}@h/wheels", None),
    ("https://h/x?token={s}&a=1", "https://h/x?token=***&a=1"),
    ("https://h/x?a=1&access_token={s}", "https://h/x?a=1&access_token=***"),
    ("https://h/x?key={s}", "https://h/x?key=***"),
    ("https://h/x?password={s}", "https://h/x?password=***"),
    ("https://h/x?x-access-token={s}", "https://h/x?x-access-token=***"),
    ("https://u:p@ss@host/x", "https://***@host/x"),
]


@pytest.mark.parametrize("template,expected", REDACT_CASES)
def test_redact_table(template: str, expected: Optional[str]) -> None:
    secret = "S3cretValue123"
    out = redact(template.format(s=secret))
    assert secret not in out
    if expected:
        assert out == expected


@pytest.mark.parametrize(
    "text",
    [
        "git+ssh://git@github.com/o/r.git",
        "ssh://git@host/o/r.git#egg=r",
        "git+https://github.com/o/r.git@v1.0#egg=r",
        "--index-url ${INDEX_URL}",
        "pkg @ ${URL}",
        "plain text with no credentials",
    ],
)
def test_redact_keeps_non_secrets(text: str) -> None:
    assert redact(text) == text


def test_redact_ssh_with_password_is_masked() -> None:
    assert "pw123" not in redact("git+ssh://git:pw123@host/o/r.git")


def test_redact_is_idempotent() -> None:
    once = redact("git+https://u:tok@h/r?token=abc&x=1")
    assert redact(once) == once


TEMPLATES = [
    "pkg @ https://user:{s}@h.example/x.whl",
    "https://{s}@h.example/path/x.tar.gz",
    "git+https://user:{s}@github.com/o/r.git#egg=../bad",
    "-e git+https://{s}@github.com/o/r.git",
    "-r https://u:{s}@h.example/req.txt",
    "-c https://u:{s}@h.example/c.txt",
    "bad name @ https://u:{s}@h.example/x",
    "pkg>=1 ; bogus >>> 'https://u:{s}@h.example'",
    "pkg @ https://h.example/x?token={s}",
    "pkg[unclosed @ https://u:{s}@h.example/x",
    "pkg @ https://h.example/x?access_token={s}#egg=a/b",
    "pkg===== https://h.example/x?key={s}",
    "--index-url https://u:{s}@h.example/simple",
    "--extra-index-url https://{s}@h.example/simple",
    "--find-links https://h.example/w?password={s}",
]


def _surfaces(exc: BaseException) -> List[str]:
    out = [str(exc), repr(exc), str(exc.args)]
    if isinstance(exc, DepKeeperError):
        out += [exc.message, repr(exc.details), *map(str, exc.details.values())]
    for attr in ("line_content", "url", "response_body", "file_path"):
        out.append(str(getattr(exc, attr, "")))
    return out


def _assert_clean(
    secret: str, caplog: pytest.LogCaptureFixture, exc: Optional[BaseException]
) -> None:
    for text in _surfaces(exc) if exc else []:
        assert secret not in text, text
    for rec in caplog.records:
        assert secret not in rec.getMessage(), rec.getMessage()
    assert secret not in caplog.text


@pytest.mark.parametrize("seed", range(40))
def test_parser_errors_and_logs_never_contain_the_secret(
    seed: int, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    rng = random.Random(seed)
    caplog.set_level(logging.DEBUG, logger="depkeeper")
    for tpl in TEMPLATES:
        secret = _secret(rng)
        line = tpl.format(s=secret)
        caplog.clear()
        err: Optional[BaseException] = None
        try:
            RequirementsParser().parse_string(line + "\n", source_file_path="r.txt")
        except Exception as exc:  # noqa: BLE001 - every type must be checked
            err = exc
        _assert_clean(secret, caplog, err)
        # Through a real file: include chains wrap the inner error text.
        (tmp_path / "inner.txt").write_text(line + "\n")
        (tmp_path / "outer.txt").write_text("-r inner.txt\n-c inner.txt\n")
        caplog.clear()
        err = None
        try:
            RequirementsParser().parse_file(str(tmp_path / "outer.txt"))
        except Exception as exc:  # noqa: BLE001
            err = exc
        _assert_clean(secret, caplog, err)


def test_exceptions_redact_at_construction() -> None:
    s = "S3cretXYZ99"
    u = "https://u:%s@h/x?token=%s" % (s, s)
    errs: List[Any] = [
        DepKeeperError("bad " + u, {"k": u}),
        ParseError("m " + u, line_content=u, file_path=u, line_number=3),
        NetworkError("m", url=u, response_body="body " + u),
    ]
    for e in errs:
        for text in _surfaces(e):
            assert s not in text
    assert errs[1].line_number == 3


def _pyproject(tmp: Path, s: str) -> Any:
    p = tmp / "pyproject.toml"
    p.write_text(
        '[project]\nname="x"\nversion="1"\ndependencies = [\n'
        '  "bad name @ https://u:%s@h.example/x",\n'
        '  "pkg @ https://h.example/x?token=%s ; ???",\n]\n' % (s, s)
    )
    return PyprojectTomlAdapter().parse(p)


def _conda_pip(tmp: Path, s: str) -> Any:
    p = tmp / "environment.yml"
    p.write_text(
        "dependencies:\n  - pip:\n    - bad name @ https://u:%s@h.example/x\n"
        "    - --index-url https://u:%s@h.example/simple\n" % (s, s)
    )
    return CondaYamlAdapter().parse(p)


def _conda_flow(tmp: Path, s: str) -> Any:
    p = tmp / "environment.yml"
    p.write_text("dependencies: [a, https://u:%s@h.example/x]\n" % s)
    return CondaYamlAdapter().parse(p)


def _conda_bad_item(tmp: Path, s: str) -> Any:
    p = tmp / "environment.yml"
    p.write_text("dependencies:\n  - https://u:%s@h.example/x\n" % s)
    return CondaYamlAdapter().parse(p)


def _conda_pip_flow(tmp: Path, s: str) -> Any:
    p = tmp / "environment.yml"
    p.write_text("dependencies:\n  - pip: [https://u:%s@h.example/x]\n" % s)
    return CondaYamlAdapter().parse(p)


@pytest.mark.parametrize(
    "build", [_pyproject, _conda_pip, _conda_flow, _conda_bad_item, _conda_pip_flow]
)
@pytest.mark.parametrize("seed", range(10))
def test_adapter_errors_and_logs_never_contain_the_secret(
    build: Callable[[Path, str], Any],
    seed: int,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.DEBUG, logger="depkeeper")
    secret = _secret(random.Random(seed))
    err: Optional[BaseException] = None
    try:
        build(tmp_path, secret)
    except Exception as exc:  # noqa: BLE001
        err = exc
    _assert_clean(secret, caplog, err)
