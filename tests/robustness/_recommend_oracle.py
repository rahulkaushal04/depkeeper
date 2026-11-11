"""Brute-force oracle and random package-history generator for recommendation tests."""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from packaging.version import InvalidVersion, Version

NOW = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)


@dataclass
class Case:
    """One random scenario: PyPI history plus every knob the checker has."""

    releases: Dict[str, Any]
    current: Optional[str]
    constraints: List[Tuple[str, str]]
    series: Optional[int]
    python: str
    min_age: Optional[timedelta]
    mode: str
    policy: Dict[str, Any] = field(default_factory=dict)
    allow_major: bool = False
    run_max_update: Optional[str] = None


def _v(s: Optional[str]) -> Optional[Version]:
    try:
        return Version(s) if s is not None else None
    except InvalidVersion:
        if s and "*" in s:
            try:
                return Version(s.rstrip("*").rstrip("."))
            except InvalidVersion:
                return None
        return None


def _triple(v: Version) -> Tuple[int, int, int]:
    r = tuple(v.release) + (0, 0, 0)
    return r[0], r[1], r[2]


def _label(cur: Version, tgt: Version, scheme: str) -> str:
    """Update label as documented (semver or calver)."""
    c, t = _triple(cur), _triple(tgt)
    names = (
        ("year", "month", "patch")
        if scheme == "calver"
        else ("major", "minor", "patch")
    )
    for i, n in enumerate(names):
        if c[i] != t[i]:
            return n
    return "update"


_RANK = {"patch": 0, "minor": 1, "month": 1, "year": 2, "major": 2}


def _gate(label: str) -> str:
    return "minor" if label in ("year", "month") else label


def detect(mode: str, current: Optional[str], stable_desc: Sequence[str]) -> str:
    """Documented auto-detection of calver."""
    if mode != "auto":
        return mode
    this_year = dt.date.today().year
    sample = current or (stable_desc[0] if stable_desc else None)
    sv = _v(sample) if sample and "*" not in sample else None
    if sv is not None and sv.release and 1990 <= sv.release[0] <= this_year + 1:
        return "calver"
    rels = [
        v.release
        for v in (Version(s) for s in stable_desc)
        if not (v.is_postrelease or v.is_devrelease)
    ]
    yy = this_year % 100

    def fits(r: Any) -> bool:
        return 1990 <= r[0] <= this_year + 1 or (
            len(r) >= 2 and 18 <= r[0] <= yy + 1 and 0 <= r[1] <= 12
        )

    for size in range(8, 41):
        window = rels[:size]
        if len(window) == size and len({r[0] for r in window}) >= 2:
            return "calver" if all(fits(r) for r in window) else "semver"
    return "semver"


def _upload(files: Any) -> Optional[datetime]:
    best: Optional[datetime] = None
    for f in files:
        raw = f.get("upload_time_iso_8601") if isinstance(f, dict) else None
        if not isinstance(raw, str):
            continue
        try:
            t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if best is None or t < best:
            best = t
    return best


def _spec_ok(specs: Sequence[Tuple[str, str]], v: Version) -> bool:
    for op, ver in specs:
        try:
            s = Specifier(f"{op}{ver}")
        except InvalidSpecifier:
            continue
        if not s.contains(v, prereleases=True):
            return False
    return True


def oracle(case: Case) -> Dict[str, Any]:
    """Independently compute rec / cooldown_skipped / major_available / scheme."""
    pol = case.policy
    live: Dict[str, Version] = {}
    times: Dict[str, Optional[datetime]] = {}
    reqpy: Dict[str, Optional[str]] = {}
    for key, files in case.releases.items():
        if not isinstance(files, list) or not files:
            continue
        if all(isinstance(f, dict) and f.get("yanked") for f in files):
            continue
        try:
            live[key] = Version(key)
        except InvalidVersion:
            continue
        times[key] = _upload(files)
        reqpy[key] = next(
            (
                f["requires_python"]
                for f in files
                if isinstance(f, dict) and f.get("requires_python")
            ),
            None,
        )
    stable_desc = [
        k
        for k, _ in sorted(live.items(), key=lambda kv: kv[1], reverse=True)
        if not live[k].is_prerelease
    ]
    scheme = detect(pol.get("versioning") or case.mode, case.current, stable_desc)
    out: Dict[str, Any] = {
        "scheme": scheme,
        "rec": None,
        "skipped": None,
        "major": None,
    }

    cur_s = case.current
    cur = _v(cur_s)
    held = bool(pol.get("hold") and cur_s)
    if held or pol.get("ignore"):
        out["rec"] = cur_s
        return out

    opted = case.allow_major or bool(pol.get("allow_major"))
    caps = [pol.get("max_update"), case.run_max_update]
    caps_set = [c for c in caps if c]
    cap = min(caps_set, key=lambda c: _RANK[c]) if caps_set else None

    def compat(k: str) -> bool:
        rp = reqpy[k]
        if not rp:
            return True
        try:
            return SpecifierSet(rp).contains(Version(case.python), prereleases=True)
        except InvalidSpecifier:
            return True

    def pool(major: Optional[int]) -> List[str]:
        res = []
        for k, v in live.items():
            if v.is_prerelease and not pol.get("allow_prerelease"):
                continue
            if major is not None and (not v.release or v.release[0] != major):
                continue
            if not compat(k) or not _spec_ok(case.constraints, v):
                continue
            res.append(k)
        return sorted(res, key=lambda k: live[k], reverse=True)

    def pick(
        cands: List[str], floor: Optional[Version]
    ) -> Tuple[Optional[str], Optional[str]]:
        if not cands:
            return None, None
        if case.min_age is None:
            return cands[0], None
        elig = []
        for k in cands:
            if floor is not None and live[k] <= floor:
                continue
            up = times[k]
            if up is None or NOW - up >= case.min_age:
                elig.append(k)
        if not elig:
            top = cands[0]
            fresh = floor is None or live[top] > floor
            return None, (top if fresh else None)
        best = elig[0]
        return best, (cands[0] if live[best] != live[cands[0]] else None)

    if cur_s:
        if scheme == "calver":
            boundary = None
        else:
            if cur is None:
                out["rec"] = None
                return out
            if not cur.release:
                out["rec"] = cur_s
                return out
            boundary = cur.release[0]
        cands = pool(None if opted else boundary)
        if cap and cur is not None:
            cands = [
                k
                for k in cands
                if live[k] <= cur
                or _RANK.get(_gate(_label(cur, live[k], scheme)), -1) <= _RANK[cap]
            ]
        if case.series:

            def sk(v: Version) -> Tuple[int, ...]:
                return (tuple(v.release) + (0,) * case.series)[: case.series]

            cands = [
                k
                for k in cands
                if cur is not None and sk(live[k]) > sk(cur) and live[k] > cur
            ]
        rec, skipped = pick(cands, cur)
        if rec is None:
            rec = cur_s
        out["rec"], out["skipped"] = rec, skipped
        if scheme != "calver" and not case.series:
            top, _ = pick(pool(None), cur)
            rv = _v(rec)
            if top and rv is not None and rv.release and live[top].release:
                if live[top].release[0] > rv.release[0]:
                    out["major"] = top
    else:
        out["rec"], out["skipped"] = pick(pool(None), None)
    return out


# ----------------------------------------------------------------- generator
_PY_REQS = [
    None,
    None,
    "",
    ">=3.6",
    ">=3.8",
    ">=3.10",
    "<3.9",
    ">=3.7,<3.12",
    "garbage",
    ">=3.8.*",
    "!=3.9.*,>=3.7",
]
_PYS = ["3.7", "3.9", "3.11", "3.12.1", "3.13"]


def _time(rng: random.Random) -> Dict[str, Any]:
    c = rng.random()
    if c < 0.15:
        return {}
    if c < 0.22:
        return {"upload_time_iso_8601": None}
    if c < 0.3:
        return {
            "upload_time_iso_8601": rng.choice(
                ["garbage", "", "2020-13-45T00:00:00Z", 12345]
            )
        }
    d = timedelta(days=rng.choice([0, 0.5, 1, 3, 6.9, 7, 7.0001, 8, 30, 400, -5]))
    t = NOW - d
    fmt = rng.choice(["z", "off", "naive", "off05"])
    if fmt == "z":
        s = t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    elif fmt == "off":
        s = t.isoformat()
    elif fmt == "naive":
        s = t.replace(tzinfo=None).isoformat()
    else:
        s = t.astimezone(timezone(timedelta(hours=5))).isoformat()
    return {"upload_time_iso_8601": s}


def _version(rng: random.Random, style: str) -> str:
    if style == "calver":
        return (
            rng.choice(["2022", "2023", "2024", "2025"])
            + f".{rng.randint(1, 12)}.{rng.randint(0, 30)}"
        )
    if style == "yymm":
        return f"{rng.randint(22, 25)}.{rng.randint(1, 12)}" + rng.choice(
            ["", ".0", ".1"]
        )
    if style == "pip":
        return f"{rng.randint(19, 25)}.{rng.randint(0, 3)}" + rng.choice(["", ".1"])
    base = f"{rng.randint(0, 4)}.{rng.randint(0, 4)}.{rng.randint(0, 4)}"
    if rng.random() < 0.15:
        base = base.rsplit(".", 1)[0]
    r = rng.random()
    if r < 0.12:
        base += rng.choice(["a", "b", "rc"]) + str(rng.randint(0, 3))
    elif r < 0.17:
        base += ".dev" + str(rng.randint(0, 3))
    elif r < 0.22:
        base += ".post" + str(rng.randint(0, 3))
    elif r < 0.25:
        base += "+local" + str(rng.randint(0, 2))
    elif r < 0.27:
        base = "1!" + base
    return base


def _files(rng: random.Random) -> List[Any]:
    r = rng.random()
    if r < 0.05:
        return []
    out: List[Any] = []
    rp = rng.choice(_PY_REQS)
    for _ in range(rng.randint(1, 3)):
        f: Dict[str, Any] = {"filename": "x"}
        f.update(_time(rng))
        if rp is not None:
            f["requires_python"] = rp
        if rng.random() < 0.12:
            f["yanked"] = True
        out.append(f)
    if rng.random() < 0.03:
        out.append("junk")
    return out


def random_case(seed: int) -> Case:
    rng = random.Random(seed)
    style = rng.choices(["semver", "calver", "yymm", "pip"], [6, 2, 1, 1])[0]
    releases: Dict[str, Any] = {}
    for _ in range(rng.randint(0, 25)):
        releases[_version(rng, style)] = _files(rng)
    if rng.random() < 0.15:
        releases[rng.choice(["foo", "1.x", "v", "1..0", "latest"])] = _files(rng)
    keys = [k for k in releases if _v(k) is not None]
    cur: Optional[str]
    c = rng.random()
    if c < 0.2 or not keys:
        cur = None
    elif c < 0.85:
        cur = rng.choice(keys)
    elif c < 0.92:
        cur = _version(rng, style)
    else:
        cur = rng.choice(["1.*", "2.*", "0.*"])
    constraints: List[Tuple[str, str]] = []
    for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])):
        op = rng.choice(["<", "<=", "!=", "==", "!=", "<", "~=", ">=", "===", ">"])
        ver = rng.choice(keys) if keys and rng.random() < 0.7 else _version(rng, style)
        if op in ("==", "!=") and rng.random() < 0.3:
            ver = ver.split(".")[0] + ".*"
        if rng.random() < 0.03:
            ver = "garbage"
        constraints.append((op, ver))
    pol: Dict[str, Any] = {}
    for k, p in (
        ("hold", 0.08),
        ("ignore", 0.05),
        ("allow_prerelease", 0.15),
        ("allow_major", 0.1),
    ):
        if rng.random() < p:
            pol[k] = True
    if rng.random() < 0.2:
        pol["max_update"] = rng.choice(["patch", "minor", "major"])
    if rng.random() < 0.1:
        pol["versioning"] = rng.choice(["auto", "semver", "calver"])
    return Case(
        releases=releases,
        current=cur,
        constraints=constraints,
        series=rng.choice([None] * 8 + [1, 2, 3]),
        python=rng.choice(_PYS),
        min_age=rng.choice(
            [
                None,
                None,
                timedelta(days=7),
                timedelta(hours=12),
                timedelta(0),
                timedelta(days=100),
            ]
        ),
        mode=rng.choice(["auto"] * 4 + ["semver", "calver"]),
        policy=pol,
        allow_major=rng.random() < 0.15,
        run_max_update=rng.choice([None, None, "patch", "minor", "major"]),
    )
