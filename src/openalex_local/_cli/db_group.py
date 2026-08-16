#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_cli/db_group.py
"""The `db` command group — verbs that act on the local database.

`update` used to sit at the top level, where the CLI audit rejects it under §1:
a bare transitive verb with no object. What it updates is the local DATABASE,
so the object becomes the group and the command reads `openalex-local db
update`.

Nesting is the sanctioned fix rather than a rename to `update-db`, because the
group is where the neighbouring verbs belong too: building the database from a
snapshot and verifying it against the upstream manifest are both coming, and
`db build` / `db verify` sit naturally beside `db update` while
`update-db` / `build-db` / `verify-db` would not.

The old top-level spelling is kept as a deprecation alias in `cli.py`. It is a
published contract — `openalex-update.service` on nas-03 invokes
`openalex-local update --yes --quiet` — so removing it outright would break a
live timer.
"""

import click

from .update import update_cmd

__all__ = ["db_group"]


@click.group("db")
def db_group() -> None:
    """Operate on the local OpenAlex database.

    \b
    Example:
      $ openalex-local db update --dry-run
      $ openalex-local db update --yes --quiet
    """


db_group.add_command(update_cmd)

# EOF
