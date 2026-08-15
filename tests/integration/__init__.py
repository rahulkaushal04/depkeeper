"""Integration tests for the depkeeper pipeline.

Unit tests pin each component's behaviour in isolation; these tests wire the
real components together — parser, version checker, dependency analyzer and the
update writer — and assert on the bytes that end up on disk.

That end-to-end shape is where the defects that actually reached users lived:
each component behaved correctly on its own, but the *handoff* between them lost
provenance (C1), lost declared ranges (M5), or wrote a version different from
the one reported (M10). Only the network layer is replaced, by
:class:`~tests.support.pypi.FakePyPIStore` serving real published release
histories.
"""
