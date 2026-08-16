#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_system_deps.py
"""openalex-local declares awscli as a SYSTEM dependency.

The declaration exists because the snapshot pipeline shells out to a bare
``aws``, which resolves against the caller's PATH. A systemd unit or cron job
gets a minimal PATH that excludes the venv's ``bin/``, so a venv-only awscli
is invisible to exactly the callers that run unattended -- measured on nas-03
2026-08-16, where the monthly update died on ``[Errno 2] ... 'aws'`` while the
venv's aws existed the whole time.

These tests assert on the DECLARATION, never on whether aws happens to be
installed in the environment running them. A test that passed only because the
developer's machine had aws would be green in exactly the environments where
this bug does not occur.
"""

import pytest

ENTRY_POINT_GROUP = "scitex_dev.system_deps"


@pytest.fixture
def declared_packages():
    """The apt package names openalex-local declares."""
    from openalex_local._system_deps import declarations

    return {dep.package for dep in declarations()}


@pytest.fixture
def declared_specs():
    """The SystemDepSpecs the entry point hands to the aggregator."""
    pytest.importorskip(
        "scitex_dev.system_deps",
        reason="keystone aggregator not installed; the raw declaration is "
        "still asserted by the other tests in this module",
    )
    from openalex_local._system_deps import provide

    return provide()


def test_awscli_is_declared(declared_packages):
    # Arrange: the fixture read the leaf's own declarations
    expected = "awscli"
    # Act
    found = expected in declared_packages
    # Assert
    assert found, (
        "awscli must be declared as a system dep; without it the snapshot "
        f"pipeline has no aws on a minimal PATH. Declared: "
        f"{sorted(declared_packages)}"
    )


def test_every_declaration_states_a_purpose():
    # Arrange
    from openalex_local._system_deps import declarations

    # Act
    unexplained = [dep.package for dep in declarations() if not dep.purpose.strip()]
    # Assert
    assert not unexplained, (
        f"declared with no purpose: {unexplained}. The aggregator renders "
        "purposes in listings and docs; an unexplained apt package is one "
        "nobody can later decide to remove."
    )


def test_provide_returns_at_least_one_spec(declared_specs):
    # Arrange: the fixture called the entry point
    count = len(declared_specs)
    # Act
    is_empty = count == 0
    # Assert
    assert not is_empty, "provide() returned nothing; the entry point is a no-op"


def test_provide_returns_scitex_dev_spec_objects(declared_specs):
    # Arrange
    from scitex_dev.system_deps import SystemDepSpec

    # Act
    wrong_type = [s for s in declared_specs if not isinstance(s, SystemDepSpec)]
    # Assert
    assert not wrong_type, (
        f"provide() must yield SystemDepSpec instances; got {wrong_type!r}. "
        "The aggregator reads typed fields, not duck-typed objects."
    )


def test_every_spec_names_this_package_as_provider(declared_specs):
    # Arrange
    from openalex_local._system_deps import PROVIDER

    # Act
    misattributed = [s.package for s in declared_specs if s.provider != PROVIDER]
    # Assert
    assert not misattributed, (
        f"specs attributed to the wrong provider: {misattributed}. The "
        "aggregator uses provider to tell an operator which leaf asked for an "
        "apt package."
    )


@pytest.fixture
def registered_entry_point_value():
    """What the installed metadata registers for this package, or a skip.

    An unregistered provider is a declaration the aggregator never sees, so
    this is worth asserting -- but only where the package is actually
    installed. Reading entry points out of an uninstalled tree returns nothing
    for reasons that have nothing to do with the declaration.
    """
    from importlib.metadata import entry_points

    names = {ep.name: ep.value for ep in entry_points(group=ENTRY_POINT_GROUP)}
    if "openalex-local" not in names:
        pytest.skip(
            "openalex-local is not installed into this environment, so its "
            "entry points are not readable; covered under an editable install"
        )
    return names["openalex-local"]


def test_entry_point_is_registered(registered_entry_point_value):
    # Arrange
    expected = "openalex_local._system_deps:provide"
    # Act
    registered = registered_entry_point_value
    # Assert
    assert registered == expected


# EOF
