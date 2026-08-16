#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_dsn.py
"""`OPENALEX_LOCAL_DB` accepts a path or a DSN, and says which it got.

The corpus is moving off a bind-mounted SQLite file onto Postgres, so the
setting has to name a PLACE without breaking every caller that passes a path.
These tests pin the three spellings and, more importantly, the refusals: a
parser that guesses is worse than one that stops, because a misread DSN
surfaces as a missing file somewhere unrelated.
"""

import os
from pathlib import Path

import pytest
from openalex_local._core.dsn import (
    Backend,
    DsnTarget,
    UnsupportedDsn,
    parse_dsn,
)


@pytest.fixture
def env_db():
    """Set OPENALEX_LOCAL_DB for one test and restore it afterwards.

    A yield fixture touching the real environment rather than a patching
    helper: the code under test reads os.environ, so the test should too.
    """
    sentinel = object()
    previous = os.environ.get("OPENALEX_LOCAL_DB", sentinel)

    def _set(value):
        os.environ["OPENALEX_LOCAL_DB"] = value

    yield _set

    if previous is sentinel:
        os.environ.pop("OPENALEX_LOCAL_DB", None)
    else:
        os.environ["OPENALEX_LOCAL_DB"] = previous


def test_bare_path_is_sqlite():
    # Arrange: the spelling every existing caller uses
    value = "/data/openalex.db"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.backend == Backend.SQLITE


def test_bare_path_keeps_the_path():
    # Arrange
    value = "/data/openalex.db"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.path == Path("/data/openalex.db")


def test_sqlite_scheme_strips_the_prefix():
    # Arrange
    value = "sqlite:///data/openalex.db"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.path == Path("/data/openalex.db")


def test_postgres_dsn_selects_postgres():
    # Arrange
    value = "postgresql://scitex@nas-03:55501/openalex"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.backend == Backend.POSTGRES


def test_postgres_dsn_keeps_the_url_verbatim():
    # Arrange: the URL must survive untouched — a normalised one sends the
    # reader looking for text they never wrote
    value = "postgresql://scitex@nas-03:55501/openalex"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.url == value


def test_postgres_dsn_carries_no_path():
    # Arrange
    value = "postgres://scitex@nas-03:55502/crossref"
    # Act
    target = parse_dsn(value)
    # Assert
    assert target.path is None


def test_empty_dsn_is_refused():
    # Arrange: an empty setting is a mistake, not a request for the default
    value = "   "

    # Act
    def _parse():
        parse_dsn(value)

    # Assert
    with pytest.raises(ValueError):
        _parse()


def test_unknown_scheme_is_refused():
    # Arrange
    value = "mysql://user@host/openalex"

    # Act
    def _parse():
        parse_dsn(value)

    # Assert
    with pytest.raises(UnsupportedDsn):
        _parse()


@pytest.fixture
def unknown_scheme_message():
    """The refusal text produced for a scheme we do not serve."""
    with pytest.raises(UnsupportedDsn) as caught:
        parse_dsn("mysql://user@host/openalex")
    return str(caught.value)


def test_unknown_scheme_message_names_what_is_supported(unknown_scheme_message):
    # Arrange: an error that only states what broke is half-written
    expected = "postgresql"
    # Act
    message = unknown_scheme_message
    # Assert
    assert expected in message


def test_sqlite_target_rejects_a_url():
    # Arrange: validation lives where the value is built
    kwargs = dict(backend=Backend.SQLITE, raw="x", path=Path("/x"), url="postgres://x")

    # Act
    def _build():
        DsnTarget(**kwargs)

    # Assert
    with pytest.raises(ValueError):
        _build()


def test_postgres_target_rejects_a_path():
    # Arrange
    kwargs = dict(
        backend=Backend.POSTGRES, raw="x", url="postgres://x", path=Path("/x")
    )

    # Act
    def _build():
        DsnTarget(**kwargs)

    # Assert
    with pytest.raises(ValueError):
        _build()


def test_unknown_backend_is_rejected_at_construction():
    # Arrange
    kwargs = dict(backend="mysql", raw="x", path=Path("/x"))

    # Act
    def _build():
        DsnTarget(**kwargs)

    # Assert
    with pytest.raises(ValueError):
        _build()


def test_get_dsn_target_returns_none_when_unset(env_db):
    # Arrange: unset means "decide for yourself", not "here is a default"
    os.environ.pop("OPENALEX_LOCAL_DB", None)
    from openalex_local._core.config import get_dsn_target

    # Act
    target = get_dsn_target()
    # Assert
    assert target is None


def test_get_dsn_target_reads_the_environment(env_db):
    # Arrange
    env_db("postgresql://scitex@nas-03:55501/openalex")
    from openalex_local._core.config import get_dsn_target

    # Act
    target = get_dsn_target()
    # Assert
    assert target.is_postgres


def test_get_db_path_refuses_a_postgres_dsn(env_db):
    """Coercing a URL into a Path yields a missing-file error that misleads."""
    # Arrange
    env_db("postgresql://scitex@nas-03:55501/openalex")
    from openalex_local._core.config import get_db_path

    # Act
    def _resolve():
        get_db_path()

    # Assert
    with pytest.raises(NotImplementedError):
        _resolve()


# EOF
