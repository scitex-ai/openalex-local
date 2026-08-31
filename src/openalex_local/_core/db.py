#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/db.py
"""Open the corpus and run SQL against it.

The corpus lives in the fleet's PostgreSQL — the one
:func:`scitex_dev.store.host_store` resolves — and nowhere else. There is no
second engine to select, no path to fall back to and no `Backend` enum in this
package, because a choice that can be made wrongly is a choice that eventually
is. `_core/dsn.py` used to own that enum; it was deleted rather than trimmed,
per the operator's 2026-08-29 ruling that a leaf package must not carry its own
database layer.

WHY THIS IS NOT A ``Store``
---------------------------
:class:`scitex_dev.store.Store` is the primitive for RUNTIME STATE: a modest
set of records, each write optimistically locked and appended to an oplog so
two hosts can converge. The corpus is not that. It is 284M immutable rows
rebuilt from an upstream snapshot, queried with joins and full-text search and
never reconciled between hosts — replaying an oplog of 284M upserts would cost
more than re-downloading the snapshot it came from.

So the primitive is used for what it is FOR, in two places rather than none:

* :func:`scitex_dev.store.host_store` resolves the DSN here. This module
  never builds a connection string, so "which database?" has exactly one
  answer fleet-wide and ``SCITEX_STORE_DSN`` moves it.
* :mod:`openalex_local._core.state` keeps the build metadata in a real
  ``Store`` — a handful of key/value records, which is precisely its shape.

Anything awkward about that split is a gap to fix in ``scitex_dev.store``,
not to paper over here.

AUTOCOMMIT IS LOAD-BEARING
--------------------------
:func:`info` probes for optional tables by querying them and catching the
failure. Inside a transaction the FIRST such failure poisons the session and
every later statement raises ``InFailedSqlTransaction`` — the probe would then
report the remaining tables absent when they are present. Autocommit gives
each statement its own transaction, so a failed probe costs only its own
answer.
"""

from __future__ import annotations

import json as _json
import threading as _threading
from contextlib import contextmanager as _contextmanager
from typing import Any, Dict, Generator, List, Optional

import psycopg as _psycopg
from psycopg.rows import dict_row as _dict_row

from .config import Config as _Config

__all__ = [
    "Database",
    "get_db",
    "close_db",
    "connection",
    "corpus_available",
]


class Database:
    """One open connection to the corpus.

    Usable directly or as a context manager. Rows come back as ``dict`` —
    the same mapping access the previous row factory offered, so a caller
    reading ``row["title"]`` is unaffected by the engine change.
    """

    def __init__(self, dsn: Optional[str] = None):
        """Open the corpus.

        Args:
            dsn: Connection string. When None, the DSN
                :func:`scitex_dev.store.host_store` resolves for this host.
        """
        self.dsn = dsn or _Config.get_dsn()
        self.conn: Optional[_psycopg.Connection] = None
        self._connect()

    def _connect(self) -> None:
        """Establish the connection."""
        self.conn = _psycopg.connect(
            self.dsn, row_factory=_dict_row, autocommit=True
        )

    def close(self) -> None:
        """Close the connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def execute(self, query: str, params: tuple = ()) -> _psycopg.Cursor:
        """Execute one statement and return its cursor."""
        return self.conn.execute(query, params)

    def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute and fetch one row, or None."""
        cursor = self.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute and fetch every row."""
        cursor = self.execute(query, params)
        return cursor.fetchall()

    def get_work(self, openalex_id: str) -> Optional[Dict[str, Any]]:
        """
        Get work data by OpenAlex ID.

        Args:
            openalex_id: OpenAlex ID (e.g., W2741809807)

        Returns:
            Work data dictionary or None
        """
        row = self.fetchone(
            "SELECT * FROM works WHERE openalex_id = %s", (openalex_id,)
        )
        if row:
            return self._row_to_dict(row)
        return None

    def get_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Get work data by DOI.

        Args:
            doi: DOI string

        Returns:
            Work data dictionary or None
        """
        row = self.fetchone("SELECT * FROM works WHERE doi = %s", (doi,))
        if row:
            return self._row_to_dict(row)
        return None

    def _row_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Copy a row to a plain dict, parsing its JSON-bearing columns.

        The columns are declared ``text`` rather than ``jsonb`` because they
        are written verbatim from the upstream snapshot and never queried
        structurally; decoding them here keeps that decision invisible to
        callers. A column that already arrives decoded (a caller that
        selected it as ``jsonb``) is passed through untouched.
        """
        result = dict(row)

        for field in ["authors_json", "concepts_json", "topics_json"]:
            if field in result and result[field]:
                result[field.replace("_json", "")] = _loads_or(result[field], [])

        if "raw_json" in result and result["raw_json"]:
            result["raw"] = _loads_or(result["raw_json"], {})

        return result

    def get_source_metrics(self, issn: str) -> Optional[Dict[str, Any]]:
        """
        Get source/journal metrics by ISSN.

        Uses SciTeX Impact Factor (OpenAlex) from precomputed table when available,
        combined with source metrics in a single optimized query.

        Args:
            issn: Journal ISSN

        Returns:
            Dictionary with scitex_if, h_index, cited_by_count or None
        """
        if not issn:
            return None

        # Single optimized query with LEFT JOIN to get both SciTeX IF and source metrics
        row = self.fetchone(
            """
            SELECT
                jif.impact_factor as scitex_if,
                jif.year as if_year,
                s.h_index as source_h_index,
                s.cited_by_count as source_cited_by_count,
                COALESCE(s.display_name, jif.journal_name) as source_name
            FROM issn_lookup l
            JOIN sources s ON l.source_id = s.id
            LEFT JOIN (
                SELECT issn, impact_factor, journal_name, year
                FROM journal_impact_factors
                WHERE issn = %s
                ORDER BY year DESC
                LIMIT 1
            ) jif ON jif.issn = l.issn
            WHERE l.issn = %s
            """,
            (issn, issn),
        )
        if row:
            return dict(row)

        # Fallback: check journal_impact_factors only (journal may not be in sources)
        row = self.fetchone(
            """
            SELECT impact_factor as scitex_if, journal_name as source_name, year as if_year
            FROM journal_impact_factors
            WHERE issn = %s
            ORDER BY year DESC
            LIMIT 1
            """,
            (issn,),
        )
        if row:
            return dict(row)

        # Final fallback: search in sources.issns JSON field
        row = self.fetchone(
            """
            SELECT h_index as source_h_index,
                   cited_by_count as source_cited_by_count,
                   display_name as source_name
            FROM sources
            WHERE issn_l = %s OR issns LIKE %s
            """,
            (issn, f'%"{issn}"%'),
        )
        if row:
            return dict(row)

        return None

    def has_table(self, name: str) -> bool:
        """Whether ``name`` resolves to a relation the current role can see.

        ``to_regclass`` answers without raising, so this is one round trip
        and needs no exception handler at the call site.
        """
        row = self.fetchone("SELECT to_regclass(%s) IS NOT NULL AS present", (name,))
        return bool(row and row["present"])

    def has_sources_table(self) -> bool:
        """Check if sources table exists."""
        return self.has_table("sources")


def _loads_or(value: Any, fallback: Any) -> Any:
    """Decode ``value`` as JSON, or return ``fallback`` when it will not."""
    if not isinstance(value, (str, bytes, bytearray)):
        return value
    try:
        return _json.loads(value)
    except (TypeError, ValueError):
        return fallback


# Thread-local storage: a psycopg connection is not safe to share across
# threads, so each thread opens its own.
_local = _threading.local()


def get_db() -> Database:
    """Get or create the calling thread's corpus connection."""
    if not hasattr(_local, "db") or _local.db is None:
        _local.db = Database()
    return _local.db


def close_db() -> None:
    """Close the calling thread's corpus connection."""
    if hasattr(_local, "db") and _local.db:
        _local.db.close()
        _local.db = None


def corpus_available() -> bool:
    """Whether the corpus is reachable AND actually holds a ``works`` table.

    Both halves matter. A reachable server with no corpus in it is the case
    that used to read as "database found" — the old check asked only whether
    a FILE existed, so an empty or half-built database counted as present and
    every query then failed one layer down, where the message names a missing
    table rather than a missing corpus.
    """
    try:
        with Database() as db:
            return db.has_table("works")
    except Exception:
        return False


@_contextmanager
def connection(dsn: Optional[str] = None) -> Generator[Database, None, None]:
    """
    Context manager for a corpus connection.

    Args:
        dsn: Connection string. If None, resolved for this host.

    Yields:
        Database instance
    """
    db = Database(dsn)
    try:
        yield db
    finally:
        db.close()

# EOF
