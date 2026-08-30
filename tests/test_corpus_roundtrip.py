#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_corpus_roundtrip.py
"""The corpus, end to end, against a real PostgreSQL.

This is the test the migration is actually judged by. Everything else in the
suite can pass while the package cannot open a database at all — these
exercise the whole path: resolve the address through the store primitive,
create the shipped schema, write a row, and read it back through the public
API.

NO MOCKS, AND NOTHING IN PRODUCTION. The server is real; it is reached through
``scitex_dev.store.testing``, which prefers a writable cluster the caller
already configured and otherwise starts a throwaway one. Every table lives in
a uniquely named SCHEMA that is dropped afterwards, so a run against the
fleet's own primary leaves nothing behind. If no writable PostgreSQL can be
reached the tests SKIP with the reason, rather than passing quietly.

WHY THE SKIP IS NOT A HOLE. A skip here is visible in the summary line and
names the route that failed. The alternative — a fake connection that always
answers — is the shape that lets a broken database layer report green, which
is exactly the failure this migration exists to end.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "database"
sys.path.insert(0, str(_SCRIPTS))

from _schema import (  # noqa: E402
    FTS_INDEX_DDL,
    WORKS_COLUMNS,
    WORKS_DDL,
    WORKS_INDEXES_DDL,
    search_vector_expression,
)

pytest.importorskip("psycopg", reason="psycopg is required to reach the corpus")

STORE_DSN_ENV = "SCITEX_STORE_DSN"


@pytest.fixture
def corpus():
    """A throwaway corpus: real PostgreSQL, private schema, dropped after.

    Points ``SCITEX_STORE_DSN`` at the private schema for the duration, so the
    package resolves to it through the same ``host_store`` call it uses in
    production — the resolution path is under test too, not bypassed.
    """
    from scitex_dev.store.testing import ephemeral_schema, writable_dsn

    from openalex_local._core.config import Config

    saved = os.environ.get(STORE_DSN_ENV)
    stack = contextlib.ExitStack()
    try:
        try:
            base = stack.enter_context(writable_dsn())
        except RuntimeError as exc:
            pytest.skip(str(exc))
        scoped = stack.enter_context(ephemeral_schema(base, prefix="openalex_test"))

        os.environ[STORE_DSN_ENV] = scoped
        Config.reset()

        import psycopg

        with psycopg.connect(scoped, autocommit=True) as conn:
            conn.execute(WORKS_DDL)
            conn.execute(WORKS_INDEXES_DDL)
            conn.execute(FTS_INDEX_DDL)

        yield scoped
    finally:
        stack.close()
        if saved is None:
            os.environ.pop(STORE_DSN_ENV, None)
        else:
            os.environ[STORE_DSN_ENV] = saved
        Config.reset()
        from openalex_local._core.db import close_db

        close_db()


def _insert_work(dsn: str, **overrides) -> dict:
    """Write one work, indexed exactly the way the build steps index one."""
    import psycopg

    record = {name: None for name in WORKS_COLUMNS}
    record.update(
        {
            "openalex_id": "W2741809807",
            "doi": "10.7717/peerj.4375",
            "title": "The state of OA",
            "abstract": "A large-scale analysis of open access articles.",
            "year": 2018,
            "type": "journal-article",
            "cited_by_count": 1500,
            "is_oa": True,
            "authors_json": '["Heather Piwowar", "Jason Priem"]',
            "concepts_json": '[{"name": "Open access", "score": 0.95}]',
            "topics_json": "[]",
            "ref_count": 0,
        }
    )
    record.update(overrides)

    columns = ", ".join(WORKS_COLUMNS)
    placeholders = ", ".join(["%s"] * len(WORKS_COLUMNS))
    vector = search_vector_expression(title="%s", abstract="%s")
    values = tuple(record[name] for name in WORKS_COLUMNS) + (
        record["title"],
        record["abstract"],
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            f"INSERT INTO works ({columns}, search_vector) "
            f"VALUES ({placeholders}, {vector})",
            values,
        )
    return record


class TestCorpusAccess:
    """Opening, reading and searching the corpus."""

    def test_the_package_resolves_to_the_test_schema(self, corpus):
        """The DSN under test is the one the package will actually use."""
        # Arrange
        from openalex_local._core.config import get_dsn

        # Act
        resolved = get_dsn()
        # Assert
        assert resolved == corpus

    def test_corpus_available_is_true_once_the_table_exists(self, corpus):
        # Arrange
        from openalex_local._core.db import corpus_available

        # Act
        available = corpus_available()
        # Assert
        assert available is True

    def test_get_work_returns_the_inserted_row(self, corpus):
        # Arrange
        _insert_work(corpus)
        from openalex_local._core.db import Database

        # Act
        with Database() as db:
            row = db.get_work("W2741809807")
        # Assert
        assert row["title"] == "The state of OA"

    def test_json_columns_are_decoded(self, corpus):
        """``authors_json`` becomes ``authors``, a real list."""
        # Arrange
        _insert_work(corpus)
        from openalex_local._core.db import Database

        # Act
        with Database() as db:
            row = db.get_work("W2741809807")
        # Assert
        assert row["authors"] == ["Heather Piwowar", "Jason Priem"]

    def test_get_work_by_doi_finds_the_row(self, corpus):
        # Arrange
        _insert_work(corpus)
        from openalex_local._core.db import Database

        # Act
        with Database() as db:
            row = db.get_work_by_doi("10.7717/peerj.4375")
        # Assert
        assert row["openalex_id"] == "W2741809807"

    def test_has_sources_table_is_false_without_one(self, corpus):
        """A probe for an absent table answers, rather than raising.

        Worth pinning: the probe runs on a connection that has just answered
        other queries, and on the previous engine an error here poisoned
        nothing. Autocommit is what preserves that, and this is the test that
        would fail if it were dropped.
        """
        # Arrange
        from openalex_local._core.db import Database

        # Act
        with Database() as db:
            present = db.has_sources_table()
        # Assert
        assert present is False


class TestFullTextSearch:
    """The full-text path, over the shipped index."""

    def test_search_finds_a_work_by_a_title_word(self, corpus):
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        result = fts.search("state of OA")
        # Assert
        assert [w.openalex_id for w in result.works] == ["W2741809807"]

    def test_search_finds_a_work_by_an_abstract_word(self, corpus):
        """The index covers the abstract, not only the title."""
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        result = fts.search("large-scale analysis")
        # Assert
        assert result.total == 1

    def test_search_misses_a_word_in_neither_field(self, corpus):
        """Negative control: the search can return nothing.

        Without this, a query that matched every row would satisfy the two
        tests above and look like a working index.
        """
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        result = fts.search("crystallography")
        # Assert
        assert result.total == 0

    def test_count_agrees_with_search(self, corpus):
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        counted = fts.count("state of OA")
        # Assert
        assert counted == 1

    def test_search_ids_returns_the_identifier(self, corpus):
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        ids = fts.search_ids("state of OA")
        # Assert
        assert ids == ["W2741809807"]

    def test_a_hyphenated_query_does_not_raise(self, corpus):
        """The old engine needed hand-quoting for these; this one does not.

        The sanitiser that did that quoting is deleted, so this pins the
        reason it could be: a query the old syntax would have rejected is
        ordinary input here.
        """
        # Arrange
        _insert_work(corpus)
        from openalex_local._core import fts

        # Act
        result = fts.search("large-scale")
        # Assert
        assert result.total == 1


class TestPublicApi:
    """The package's own entry points, over the same corpus."""

    def test_get_returns_a_work(self, corpus):
        # Arrange
        _insert_work(corpus)
        import openalex_local

        openalex_local._core.config.Config.set_mode("db")
        # Act
        work = openalex_local.get("W2741809807")
        # Assert
        assert work.title == "The state of OA"

    def test_exists_is_true_for_a_present_id(self, corpus):
        # Arrange
        _insert_work(corpus)
        import openalex_local

        openalex_local._core.config.Config.set_mode("db")
        # Act
        present = openalex_local.exists("W2741809807")
        # Assert
        assert present is True

    def test_exists_is_false_for_an_absent_id(self, corpus):
        # Arrange
        _insert_work(corpus)
        import openalex_local

        openalex_local._core.config.Config.set_mode("db")
        # Act
        present = openalex_local.exists("W0000000000")
        # Assert
        assert present is False

    def test_info_reports_the_dsn_it_used(self, corpus):
        # Arrange
        _insert_work(corpus)
        import openalex_local

        openalex_local._core.config.Config.set_mode("db")
        # Act
        reported = openalex_local.info()
        # Assert
        assert reported["dsn"] == corpus


class TestBuildMetadataStore:
    """Build counters live in a real ``scitex_dev.store.Store``."""

    def test_a_counter_round_trips(self, corpus):
        # Arrange
        from openalex_local._core.state import get_metadata, set_metadata

        # Act
        set_metadata("total_works", "284000000")
        recorded = get_metadata("total_works")
        # Assert
        assert recorded == "284000000"

    def test_a_counter_can_be_overwritten(self, corpus):
        """Each build step recomputes its counter; the newest value wins."""
        # Arrange
        from openalex_local._core.state import get_metadata, set_metadata

        set_metadata("fts_total_indexed", "1")
        # Act
        set_metadata("fts_total_indexed", "2")
        recorded = get_metadata("fts_total_indexed")
        # Assert
        assert recorded == "2"

    def test_an_unrecorded_counter_is_none(self, corpus):
        """Negative control: reading answers, rather than inventing a value."""
        # Arrange
        from openalex_local._core.state import get_metadata

        # Act
        recorded = get_metadata("never_written")
        # Assert
        assert recorded is None

    def test_info_prefers_the_recorded_counter(self, corpus):
        """The counter is what makes ``info()`` cheap on a 284M-row corpus."""
        # Arrange
        _insert_work(corpus)
        import openalex_local
        from openalex_local._core.state import set_metadata

        openalex_local._core.config.Config.set_mode("db")
        set_metadata("total_works", "284000000")
        # Act
        reported = openalex_local.info()
        # Assert
        assert reported["work_count"] == 284000000

# EOF
