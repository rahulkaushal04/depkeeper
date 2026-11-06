"""Integration tests for the depkeeper pipeline.

Unit tests pin each component's behaviour in isolation; these tests wire the
real components together — parser, version checker, dependency analyzer and the
update writer — and assert on the bytes that end up on disk.

That end-to-end shape catches handoff defects between components: lost
provenance, lost declared ranges, or a written version that differs from the
one reported. Only the network layer is replaced, by
:class:`~tests.support.pypi.FakePyPIStore` serving real published release
histories.
"""
