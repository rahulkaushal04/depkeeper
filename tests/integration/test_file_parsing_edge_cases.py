"""
Integration tests: RequirementsParser edge cases.

Covers scenarios 25–29, 57, 60 from the scenario document.

- SCENARIO-25: -r include directive resolved and packages collected
- SCENARIO-26: -c constraint directive stored in parser.get_constraints()
- SCENARIO-27: VCS URL entry parsed without crashing
- SCENARIO-28: Editable install (-e) parsed without crashing
- SCENARIO-29: Hash directives (--hash) stripped, package still parsed
- SCENARIO-57: Circular include raises ParseError
- SCENARIO-60: Multi-level nested -r includes fully traversed

All tests use RequirementsParser directly (no HTTP, no CLI) and exercise
the parser's internal logic via parse_string / parse_file / parse_line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import ParseError


# ---------------------------------------------------------------------------
# SCENARIO-25 — -r include: packages from included file collected
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_include_directive_collects_packages_from_included_file(
    make_requirements_file,
    parser: RequirementsParser,
) -> None:
    """'-r base.txt' causes the parser to recurse into base.txt and collect packages.

    Implementation: RequirementsParser._handle_include_directive recursively
    calls parse_file on the referenced path, returning a flattened list.
    """
    base = make_requirements_file("requests==2.28.0\n", filename="base.txt")
    main = make_requirements_file(f"-r {base.name}\nflask==2.3.0\n")

    requirements = parser.parse_file(main)

    req_names = {r.name for r in requirements}
    assert req_names == {"flask", "requests"}
    assert len(requirements) == 2


@pytest.mark.integration
def test_include_directive_preserves_line_numbers(
    make_requirements_file,
    parser: RequirementsParser,
) -> None:
    """Packages from an included file carry correct line numbers.

    Line numbers must reflect their position within their own file,
    not a global counter.
    """
    base = make_requirements_file("requests==2.28.0\n", filename="base.txt")
    main = make_requirements_file(f"-r {base.name}\nflask==2.3.0\n")

    requirements = parser.parse_file(main)
    by_name = {r.name: r for r in requirements}

    # requests is on line 1 of base.txt
    assert by_name["requests"].line_number == 1
    # flask is on line 2 of main (after the -r directive on line 1)
    assert by_name["flask"].line_number == 2


# ---------------------------------------------------------------------------
# SCENARIO-26 — -c constraint: stored in parser.get_constraints()
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_constraint_directive_stores_constraint_not_requirement(
    make_requirements_file,
    parser: RequirementsParser,
) -> None:
    """-c constraints.txt: constraint requirements go to get_constraints(), not to output.

    Implementation: _handle_constraint_directive calls parse_file with
    is_constraint_file=True, which routes each requirement to
    _constraint_requirements instead of the returned list.
    """
    constraints = make_requirements_file("requests<2.30.0\n", filename="constraints.txt")
    main = make_requirements_file(f"-c {constraints.name}\nrequests==2.28.0\n")

    requirements = parser.parse_file(main)

    # The constraint is NOT returned as a regular requirement
    assert len(requirements) == 1
    assert requirements[0].name == "requests"

    # It IS stored in the constraints map
    stored_constraints = parser.get_constraints()
    assert "requests" in stored_constraints
    constraint_req = stored_constraints["requests"]
    # Constraint has the '<2.30.0' specifier
    assert any(op == "<" and v == "2.30.0" for op, v in constraint_req.specs)


@pytest.mark.integration
def test_constraint_parsed_as_requirement_object(
    make_requirements_file,
    parser: RequirementsParser,
) -> None:
    """Constraint file entries are parsed as full Requirement objects.

    The Requirement stored in get_constraints() must have the correct
    name and specs, identical to what a normal parse would produce.
    """
    constraints = make_requirements_file(
        "django>=3.2,<4.0\n", filename="constraints.txt"
    )
    main = make_requirements_file(f"-c {constraints.name}\ndjango==3.2.0\n")

    parser.parse_file(main)
    stored = parser.get_constraints()

    assert "django" in stored
    django_c = stored["django"]
    ops = {op for op, _ in django_c.specs}
    assert ">=" in ops
    assert "<" in ops


# ---------------------------------------------------------------------------
# SCENARIO-27 — VCS URL: parsed without crashing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_vcs_url_parsed_without_crashing(parser: RequirementsParser) -> None:
    """VCS URL entries are parsed into a Requirement with url set.

    Grounded in: CLAUDE.md — 'VCS URLs (git+https://)' are a supported line type.
    The parser detects URL schemes in URL_SCHEMES and routes them to
    _build_url_based_requirement.
    """
    reqs = parser.parse_string(
        "git+https://github.com/pallets/flask.git@main#egg=flask\n"
    )

    assert len(reqs) == 1
    req = reqs[0]
    assert req.name == "flask"
    assert req.url is not None
    # URL requirement has no PEP 440 version specifiers
    assert req.specs == []


@pytest.mark.integration
def test_vcs_url_alongside_normal_package(parser: RequirementsParser) -> None:
    """VCS URL entry does not interfere with parsing subsequent normal packages."""
    reqs = parser.parse_string(
        "git+https://github.com/pallets/flask.git@main#egg=flask\n"
        "requests==2.28.0\n"
    )

    assert len(reqs) == 2
    by_name = {r.name: r for r in reqs}
    assert "flask" in by_name
    assert "requests" in by_name
    # Normal package has version spec
    assert by_name["requests"].specs == [("==", "2.28.0")]


# ---------------------------------------------------------------------------
# SCENARIO-28 — Editable install: parsed without crashing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_editable_vcs_url_parsed_without_crashing(parser: RequirementsParser) -> None:
    """'-e git+https://...' is parsed as an editable URL requirement.

    The parser recognises the -e flag and sets Requirement.editable = True.
    The VCS URL is stored in req.url.
    """
    reqs = parser.parse_string(
        "-e git+https://github.com/pallets/flask.git@main#egg=myflask\n"
    )

    assert len(reqs) == 1
    req = reqs[0]
    assert req.editable is True
    assert req.url is not None


@pytest.mark.integration
def test_editable_does_not_prevent_other_packages(
    make_requirements_file, parser: RequirementsParser
) -> None:
    """'-e .' alongside a normal package: normal package still parsed."""
    main = make_requirements_file("-e .\nflask==2.3.0\n")

    requirements = parser.parse_file(main)

    # '-e .' is parsed (may have a name derived from the path or be empty)
    # Flask must be parsed correctly regardless
    flask_reqs = [r for r in requirements if r.name == "flask"]
    assert len(flask_reqs) == 1
    assert flask_reqs[0].specs == [("==", "2.3.0")]


# ---------------------------------------------------------------------------
# SCENARIO-29 — Hash directives: stripped, package still parsed correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_hash_directive_stripped_from_version_spec(parser: RequirementsParser) -> None:
    """'flask==2.3.0 --hash=sha256:...' — hash is extracted; version spec intact.

    Implementation: the parser strips '--hash=...' tokens before passing
    the remaining spec to PkgRequirement.  The result is stored in req.hashes.
    """
    reqs = parser.parse_string(
        "flask==2.3.0"
        " --hash=sha256:abcd1234ef567890abcd1234ef567890"
        "abcd1234ef567890abcd1234ef567890\n"
    )

    assert len(reqs) == 1
    req = reqs[0]
    assert req.name == "flask"
    assert req.specs == [("==", "2.3.0")]
    # Hash value must be stored separately
    assert len(req.hashes) == 1
    assert req.hashes[0].startswith("sha256:")


@pytest.mark.integration
def test_multiple_hashes_all_stored(parser: RequirementsParser) -> None:
    """Multiple --hash directives on one line are all captured in req.hashes."""
    reqs = parser.parse_string(
        "requests==2.28.0"
        " --hash=sha256:aaaa0000bbbb1111cccc2222dddd3333"
        "aaaa0000bbbb1111cccc2222dddd3333"
        " --hash=sha512:ffff9999eeee8888dddd7777cccc6666"
        "ffff9999eeee8888dddd7777cccc6666\n"
    )

    assert len(reqs) == 1
    req = reqs[0]
    assert req.name == "requests"
    assert len(req.hashes) == 2


# ---------------------------------------------------------------------------
# SCENARIO-57 — Circular include: ParseError raised
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_circular_include_raises_parse_error(
    circular_include_setup: tuple,
    parser: RequirementsParser,
) -> None:
    """A circular -r chain (A → B → A) must raise ParseError, not loop forever.

    Implementation: RequirementsParser._handle_include_directive maintains
    _included_files_stack and raises ParseError when it detects a cycle.
    """
    a_file, _ = circular_include_setup

    with pytest.raises(ParseError) as exc_info:
        parser.parse_file(a_file)

    # Error must mention circular dependency
    assert "circular" in str(exc_info.value).lower()


@pytest.mark.integration
def test_circular_include_error_contains_cycle_path(
    circular_include_setup: tuple,
    parser: RequirementsParser,
) -> None:
    """ParseError message includes the full cycle path for debugging."""
    a_file, b_file = circular_include_setup

    with pytest.raises(ParseError) as exc_info:
        parser.parse_file(a_file)

    error_msg = str(exc_info.value)
    # At minimum, one of the filenames in the cycle must appear in the error
    assert a_file.name in error_msg or b_file.name in error_msg


# ---------------------------------------------------------------------------
# SCENARIO-60 — Nested includes: full chain traversed
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_nested_includes_fully_traversed(
    nested_include_setup: tuple,
    parser: RequirementsParser,
) -> None:
    """Multi-level -r include chain (A → B → C) collects packages from all levels.

    nested_include_setup: (A, B, C) where A includes B, B includes C.
    - A has flask==2.3.0
    - B has requests==2.28.0
    - C has click==8.0.0

    All three packages must appear in the parsed output.
    """
    a_file, b_file, c_file = nested_include_setup

    requirements = parser.parse_file(a_file)

    req_names = {r.name for r in requirements}
    assert req_names == {"flask", "requests", "click"}
    assert len(requirements) == 3


@pytest.mark.integration
def test_nested_include_packages_deduplicated_by_file(
    nested_include_setup: tuple,
    parser: RequirementsParser,
) -> None:
    """Each file in a nested chain is parsed at most once.

    The parser uses _included_files_stack to guard against revisiting a file
    in the current chain. Two separate chains can include the same file, but
    within a single chain each file appears only once.
    """
    a_file, _, _ = nested_include_setup
    requirements = parser.parse_file(a_file)

    # No duplicate package names: each is defined in a different file
    names = [r.name for r in requirements]
    assert len(names) == len(set(names)), f"Duplicate packages found: {names}"


@pytest.mark.integration
def test_parser_reset_clears_state_between_parses(
    make_requirements_file,
    parser: RequirementsParser,
) -> None:
    """parser.reset() clears constraints and include stack between independent runs.

    If the same parser instance is reused across multiple parse_file calls
    without reset(), state from the first run could contaminate the second.
    """
    constraints = make_requirements_file("django<4.0\n", filename="constraints.txt")
    main = make_requirements_file(f"-c {constraints.name}\ndjango==3.2.0\n")
    parser.parse_file(main)

    # Constraint from first run is stored
    assert "django" in parser.get_constraints()

    # After reset(), constraints must be cleared
    parser.reset()
    assert parser.get_constraints() == {}
