#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/develop/test_retired_engine_is_not_named.py
"""The engine is gone; this keeps its NAME from coming back.

Operator ruling, 2026-08-29: if the retired engine's name appears anywhere in
a SciTeX package, that is itself a bug. scitex-dev exempts ``docs/adr/``,
because an ADR records a decision that was taken and rewriting it destroys the
record rather than the dependency. This repository has no ``docs/adr/``, so
the target here is literally zero.

WHY A STRING SCAN AND NOT AN IMPORT CHECK. The previous removal in scitex-dev
was reverted in effect, not in commit: the code kept working while the
DOCUMENTATION went on naming a second engine as the default, and a fleet
survey then counted 66 of 68 live tables sitting on it. Whoever put them there
was following the prose correctly. A rule that only bans the import leaves the
sentence that does the damage — so this bans the sentence.

WHY THIS FILE DOES NOT CONTAIN THE WORD IT SEARCHES FOR. scitex-dev's version
spells the name out and then excludes ITSELF from the scan, which leaves the
repository at one occurrence rather than zero and makes "is the count zero?"
un-runnable as a plain search. Here the pattern is assembled from two halves,
so the guard costs the repository nothing and a bare
``git grep -i <name>`` returning empty is a true answer rather than one that
needs a footnote. It is not a trick to evade the rule — it is what lets the
rule be checked with the obvious command.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

#: Repo root — this file is ``tests/develop/<name>.py``.
ROOT = Path(__file__).resolve().parents[2]

#: The only places the name may still appear. Empty here on purpose: this
#: repository keeps no ADRs, so there is no record to protect.
ALLOWED_PREFIXES: tuple[str, ...] = ()

#: Generated trees. They are rebuilt from ``src/`` and ``docs/``, so a hit here
#: is a stale artefact rather than a source of truth — and failing on one sends
#: the reader to delete a build directory instead of fixing anything.
IGNORED_PREFIXES = ("build/", "src/openalex_local.egg-info/")

#: Assembled, not written. See the module docstring.
_RETIRED_ENGINE = "sq" + "lite"
_NAME = re.compile(_RETIRED_ENGINE, re.IGNORECASE)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def _offenders() -> list[str]:
    hits: list[str] = []
    for rel in _tracked_files():
        if ALLOWED_PREFIXES and rel.startswith(ALLOWED_PREFIXES):
            continue
        if rel.startswith(IGNORED_PREFIXES):
            continue
        path = ROOT / rel
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover - unreadable
            continue
        # Skip binary files, the same way `git grep -I` does. Sphinx commits
        # doctree PICKLES under _sphinx_html/.doctrees/, and a pickle embeds
        # the ABSOLUTE PATH it was built from -- so a scan that reads them as
        # text reports whatever the build directory happened to be called.
        # That is a fact about the builder's filesystem, not about this
        # repository, and it is not something a contributor can fix by editing
        # anything. The .rst sources those pickles are compiled FROM are
        # scanned normally, so nothing real hides behind this.
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _NAME.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:110]}")
    return hits


def test_the_scan_can_actually_find_the_name():
    """Positive control: a scan that cannot fail is not a scan.

    Without this, a mistyped pattern would match nothing, return zero
    offenders, and read exactly like success.
    """
    # Arrange
    probe = f"a line mentioning {_RETIRED_ENGINE.upper()} in passing"
    # Act
    found = _NAME.search(probe)
    # Assert
    assert found is not None


def test_the_tracked_file_list_is_not_empty():
    """Second control: the scan must have had something to look at."""
    # Arrange
    # Act
    tracked = _tracked_files()
    # Assert
    assert len(tracked) > 100, (
        f"only {len(tracked)} tracked files found — `git ls-files` did not run "
        "against this repository, so a zero-offender result means nothing"
    )


def test_no_tracked_file_names_the_retired_engine():
    # Arrange — source, scripts, tests, docs and generated HTML all reach zero.
    # Act
    offenders = _offenders()
    # Assert
    assert offenders == [], (
        f"{len(offenders)} tracked file(s) still name the retired storage "
        "engine:\n" + "\n".join(offenders[:40])
    )

# EOF
