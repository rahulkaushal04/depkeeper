"""CLI subcommand implementations for depkeeper.

Each module in this package defines one Click command and its orchestration
logic. Commands are registered on the root group in :mod:`depkeeper.cli`
rather than re-exported here, so importing this package never pulls in the
whole CLI.
"""
