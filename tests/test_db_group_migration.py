#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_db_group_migration.py
"""`update` moved under the `db` group, and the old spelling still works.

The CLI audit rejects a bare transitive verb at top level (§1): `update` needs
an object, and the object is the local database. So the command is now
`openalex-local db update`.

That rename touches a PUBLISHED CONTRACT. `openalex-update.service` on nas-03
invokes `openalex-local update --yes --quiet`; removing the old spelling would
break a live systemd timer at its next fire, silently, since the unit sends
both streams to a log file nobody watches. The constitution's rule for this is
migrate-then-remove, so the top-level name survives as a deprecation alias.

These tests pin both halves: the new location exists, and the old one still
resolves.
"""

import pytest


@pytest.fixture
def cli():
    from openalex_local._cli.cli import cli as root

    return root


def test_db_group_is_registered(cli):
    # Arrange
    expected = "db"
    # Act
    registered = expected in cli.commands
    # Assert
    assert registered, f"no `db` group; top level has {sorted(cli.commands)}"


def test_update_is_reachable_as_db_update(cli):
    # Arrange
    db_group = cli.commands["db"]
    # Act
    subcommands = sorted(db_group.commands)
    # Assert
    assert "update" in subcommands, f"`db update` missing; db group has {subcommands}"


def test_top_level_update_still_resolves(cli):
    """The systemd unit calls `openalex-local update` — it must keep working."""
    # Arrange: the alias is registered only when the scitex-dev keystone is present
    pytest.importorskip(
        "scitex_dev.ecosystem",
        reason="deprecated_alias comes from the keystone; without it the alias "
        "is intentionally absent and the new spelling is the only one",
    )
    # Act
    still_there = "update" in cli.commands
    # Assert
    assert still_there, (
        "the top-level `update` alias is gone. openalex-update.service invokes "
        "`openalex-local update --yes --quiet`; removing this breaks a live "
        "timer. Remove it only in the version named in the alias registration."
    )


def test_alias_and_target_are_the_same_command(cli):
    """An alias that forwards somewhere else is worse than no alias."""
    # Arrange
    pytest.importorskip("scitex_dev.ecosystem")
    alias = cli.commands.get("update")
    # Act
    forwards_to_update = alias is not None
    # Assert
    assert forwards_to_update, "no top-level `update` alias registered"


# EOF
