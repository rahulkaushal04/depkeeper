"""Recent-history calver auto-detection against real release lists."""

import datetime as dt
from typing import List

import pytest

from depkeeper.utils.version_utils import detect_versioning

YY = dt.date.today().year % 100

# Newest-first stable releases captured from PyPI.
REAL = [
    (
        "pip",
        [
            "26.3",
            "26.2.2",
            "26.2.1",
            "26.2",
            "26.1.2",
            "26.1.1",
            "26.1",
            "26.0.1",
            "26.0",
            "25.3",
            "25.2",
            "25.1.1",
            "25.1",
            "25.0.1",
        ],
        "calver",
    ),
    (
        "packaging",
        [
            "26.3",
            "26.2",
            "26.1",
            "26.0",
            "25.0",
            "24.2",
            "24.1",
            "24.0",
            "23.2",
            "23.1",
            "23.0",
            "22.0",
            "21.3",
            "21.2",
        ],
        "calver",
    ),
    (
        "attrs",
        [
            "26.1.0",
            "25.4.0",
            "25.3.0",
            "25.2.0",
            "25.1.0",
            "24.3.0",
            "24.2.0",
            "24.1.0",
            "23.2.0",
            "23.1.0",
            "22.2.0",
            "22.1.0",
            "21.4.0",
            "21.3.0",
        ],
        "calver",
    ),
    (
        "black",
        [
            "26.10.1",
            "26.10.0",
            "26.5.1",
            "26.5.0",
            "26.3.1",
            "26.3.0",
            "26.1.0",
            "25.12.0",
            "25.11.0",
            "25.9.0",
            "25.1.0",
            "24.10.0",
            "24.8.0",
            "24.4.2",
        ],
        "calver",
    ),
    (
        "certifi",
        [
            "2026.10.23",
            "2026.10.19",
            "2026.10.18",
            "2026.7.22",
            "2026.6.17",
            "2026.5.20",
            "2026.4.22",
            "2026.2.25",
            "2026.1.4",
            "2025.11.12",
            "2025.10.5",
            "2025.8.3",
            "2025.7.14",
            "2025.7.9",
        ],
        "calver",
    ),
    (
        "tzdata",
        [
            "2026.6",
            "2026.5",
            "2026.4",
            "2026.3",
            "2026.2",
            "2026.1",
            "2025.3",
            "2025.2",
            "2025.1",
            "2024.2",
            "2024.1",
            "2023.4",
            "2023.3",
            "2023.2",
        ],
        "calver",
    ),
    (
        "pytz",
        [
            "2026.6",
            "2026.5",
            "2026.4",
            "2026.3",
            "2026.2",
            "2026.1",
            "2025.2",
            "2025.1",
            "2024.2",
            "2024.1",
            "2023.4",
            "2023.3",
            "2023.2",
            "2022.7.1",
        ],
        "calver",
    ),
    (
        "setuptools",
        [
            "84.2.1",
            "84.2.0",
            "84.1.0",
            "84.0.0",
            "83.0.0",
            "82.0.1",
            "82.0.0",
            "81.0.0",
            "80.10.2",
            "80.10.1",
            "80.9.0",
            "80.8.0",
            "80.7.1",
            "80.6.0",
        ],
        "semver",
    ),
    (
        "cryptography",
        [
            "50.0.2",
            "50.0.1",
            "50.0.0",
            "49.0.0",
            "48.0.1",
            "48.0.0",
            "47.0.0",
            "46.0.7",
            "46.0.6",
            "46.0.5",
            "46.0.4",
            "46.0.3",
            "46.0.2",
            "46.0.1",
        ],
        "semver",
    ),
    (
        "pytest",
        [
            "9.2.0",
            "9.1.1",
            "9.1.0",
            "9.0.3",
            "9.0.2",
            "9.0.1",
            "9.0.0",
            "8.4.2",
            "8.4.1",
            "8.4.0",
            "8.3.5",
            "8.3.4",
            "8.3.3",
            "8.3.2",
        ],
        "semver",
    ),
    (
        "rich",
        [
            "15.0.0",
            "14.3.4",
            "14.3.3",
            "14.3.2",
            "14.3.1",
            "14.3.0",
            "14.2.0",
            "14.1.0",
            "14.0.0",
            "13.9.4",
            "13.9.3",
            "13.9.2",
            "13.9.1",
            "13.9.0",
        ],
        "semver",
    ),
    (
        "numpy",
        [
            "2.5.4",
            "2.5.3",
            "2.5.2",
            "2.5.1",
            "2.5.0",
            "2.4.6",
            "2.4.5",
            "2.4.4",
            "2.4.3",
            "2.4.2",
            "2.4.1",
            "2.3.5",
            "2.3.4",
            "2.3.3",
        ],
        "semver",
    ),
    (
        "django",
        [
            "6.1.3",
            "6.1.2",
            "6.1.1",
            "6.1",
            "6.0.10",
            "6.0.9",
            "6.0.8",
            "6.0.7",
            "6.0.6",
            "6.0.5",
            "6.0.4",
            "6.0.3",
            "6.0.2",
            "6.0.1",
        ],
        "semver",
    ),
    (
        "boto3",
        [
            "1.44.0",
            "1.43.127",
            "1.43.126",
            "1.43.125",
            "1.43.124",
            "1.43.123",
            "1.43.122",
            "1.43.121",
            "1.43.120",
            "1.43.119",
            "1.43.118",
            "1.43.117",
            "1.43.116",
            "1.43.115",
        ],
        "semver",
    ),
    (
        "urllib3",
        [
            "2.8.0",
            "2.7.0",
            "2.6.3",
            "2.6.2",
            "2.6.1",
            "2.6.0",
            "2.5.0",
            "2.4.0",
            "2.3.0",
            "2.2.3",
            "2.2.2",
            "2.2.1",
            "2.2.0",
            "2.1.0",
        ],
        "semver",
    ),
    (
        "pydantic",
        [
            "2.14.3",
            "2.14.2",
            "2.14.1",
            "2.14.0",
            "2.13.5",
            "2.13.4",
            "2.13.3",
            "2.13.2",
            "2.13.1",
            "2.13.0",
            "2.12.5",
            "2.12.4",
            "2.12.3",
            "2.12.2",
        ],
        "semver",
    ),
    (
        "click",
        [
            "8.5.1",
            "8.5.0",
            "8.4.2",
            "8.4.1",
            "8.4.0",
            "8.3.3",
            "8.3.2",
            "8.3.1",
            "8.3.0",
            "8.2.1",
            "8.2.0",
            "8.1.8",
            "8.1.7",
            "8.1.6",
        ],
        "semver",
    ),
    (
        "requests",
        [
            "2.34.2",
            "2.34.1",
            "2.34.0",
            "2.33.1",
            "2.33.0",
            "2.32.5",
            "2.32.4",
            "2.32.3",
            "2.32.2",
            "2.31.0",
            "2.30.0",
            "2.29.0",
            "2.28.2",
            "2.28.1",
        ],
        "semver",
    ),
    (
        "flask",
        [
            "3.1.3",
            "3.1.2",
            "3.1.1",
            "3.1.0",
            "3.0.3",
            "3.0.2",
            "3.0.1",
            "3.0.0",
            "2.3.3",
            "2.3.2",
            "2.3.1",
            "2.3.0",
            "2.2.5",
            "2.2.4",
        ],
        "semver",
    ),
    (
        "virtualenv",
        [
            "21.15.6",
            "21.15.5",
            "21.15.4",
            "21.15.3",
            "21.15.2",
            "21.15.1",
            "21.15.0",
            "21.14.13",
            "21.14.12",
            "21.14.11",
            "21.14.10",
            "21.14.9",
            "21.14.8",
            "21.14.7",
        ],
        "semver",
    ),
    (
        "wheel",
        [
            "0.48.0",
            "0.47.0",
            "0.46.3",
            "0.46.2",
            "0.45.1",
            "0.45.0",
            "0.44.0",
            "0.43.0",
            "0.42.0",
            "0.41.3",
            "0.41.2",
            "0.41.1",
            "0.41.0",
            "0.40.0",
        ],
        "semver",
    ),
    # virtualenv 20.x era: constant leading component 20.
    (
        "virtualenv-20",
        [
            "20.30.0",
            "20.29.3",
            "20.29.2",
            "20.29.1",
            "20.29.0",
            "20.28.1",
            "20.28.0",
            "20.27.1",
            "20.27.0",
            "20.26.6",
        ],
        "semver",
    ),
]


@pytest.mark.parametrize("name,history,expected", REAL, ids=[r[0] for r in REAL])
def test_real_histories(name: str, history: List[str], expected: str) -> None:
    assert detect_versioning("auto", history[-1], history) == expected


def test_old_semver_history_before_calver_switch_is_ignored() -> None:
    pip = ["23.3.2", "23.3.1", "23.2", "23.1", "23.0", "22.3", "22.2", "22.1"]
    old = ["10.0.1", "9.0.3", "8.1.2", "1.5.6"]
    assert detect_versioning("auto", "23.0", pip + old) == "calver"
    assert detect_versioning("auto", "23.0", old + pip) == "calver"  # order-free


def _cal(*pairs: str) -> List[str]:
    return list(pairs)


def test_needs_eight_recent_releases() -> None:
    seven = [f"{YY}.{m}" for m in (3, 2, 1)] + [
        f"{YY - 1}.{m}" for m in (12, 11, 10, 9)
    ]
    assert detect_versioning("auto", None, seven) == "semver"
    assert detect_versioning("auto", None, seven + [f"{YY - 1}.8"]) == "calver"


def test_needs_two_leading_components() -> None:
    assert detect_versioning("auto", None, [f"{YY}.{m}" for m in range(1, 10)]) == (
        "semver"
    )
    # a second year is found further back, still all calendar-shaped
    deep = [f"{YY}.{m}" for m in range(9, 0, -1)] + [f"{YY - 1}.12"]
    assert detect_versioning("auto", None, deep) == "calver"


def test_non_date_inside_recent_window_blocks() -> None:
    ok = [f"{YY}.{m}" for m in (4, 3, 2, 1)] + [
        f"{YY - 1}.{m}" for m in (12, 11, 10, 9)
    ]
    assert detect_versioning("auto", None, ok) == "calver"
    assert (
        detect_versioning("auto", None, ok[:5] + [f"{YY - 1}.13"] + ok[5:]) == "semver"
    )
    assert detect_versioning("auto", None, ok + ["17.1", "3.0"]) == "calver"
    assert detect_versioning("auto", None, [f"{YY + 2}.1"] + ok) == "semver"
    assert detect_versioning("auto", None, [f"{YY + 1}.1"] + ok) == "calver"


def test_prereleases_post_dev_and_junk_ignored() -> None:
    ok = [f"{YY}.{m}" for m in (4, 3, 2, 1)] + [
        f"{YY - 1}.{m}" for m in (12, 11, 10, 9)
    ]
    noise = ["99.0rc1", "3.0.dev1", "1.0.post1", f"{YY}.99.post2", "not-a-version"]
    assert detect_versioning("auto", None, noise + ok) == "calver"


def test_epoch_does_not_hide_release() -> None:
    ok = [f"1!{YY}.{m}" for m in (4, 3, 2, 1)] + [
        f"{YY - 1}.{m}" for m in (12, 11, 10, 9)
    ]
    assert detect_versioning("auto", None, ok) == "calver"


def test_explicit_override_beats_history() -> None:
    pip = [f"{YY}.{m}" for m in (4, 3, 2, 1)] + [
        f"{YY - 1}.{m}" for m in (12, 11, 10, 9)
    ]
    assert detect_versioning("semver", "23.0", pip) == "semver"
    assert detect_versioning("calver", "1.0", ["1.0", "2.0"]) == "calver"
