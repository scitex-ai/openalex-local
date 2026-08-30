#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/fts.py
"""Full-text search over the corpus, using PostgreSQL's own index.

``works.search_vector`` is a ``tsvector`` built from the title and abstract
and covered by a GIN index (see ``scripts/database/03_build_fts_index.py``);
matching is ``@@`` against a parsed query. There is no separate index table
to join against any more, which removes a whole class of failure: the old
external index was keyed on a row identifier the corpus table did not
declare, so a rebuild that renumbered the corpus silently returned the WRONG
work for every hit.

WHY ``websearch_to_tsquery`` AND NOT A SANITISER
------------------------------------------------
The previous implementation quoted the user's words itself whenever it spotted
a hyphen or punctuation, because an unbalanced operator was a hard error in the
old engine's query syntax. ``websearch_to_tsquery`` takes the syntax users
already know — bare words, ``"quoted phrases"``, ``or``, leading ``-`` to
exclude — and, crucially, never raises on malformed input. So the guessing
heuristic is deleted rather than ported: it existed to prevent an exception
that can no longer occur, and it changed the meaning of any query containing a
hyphen while doing so.
"""

import time as _time
from typing import List, Optional

from .db import Database, get_db
from .models import SearchResult, Work

__all__ = [
    "search",
    "count",
    "search_ids",
]

#: The text-search configuration the index was built with. Matching MUST use
#: the same one: a query parsed under a different configuration stems words
#: differently and silently misses rows the index does contain.
TEXT_SEARCH_CONFIG = "english"

_MATCH = "search_vector @@ websearch_to_tsquery(%s, %s)"


def search(
    query: str,
    limit: int = 20,
    offset: int = 0,
    db: Optional[Database] = None,
) -> SearchResult:
    """
    Full-text search across works.

    Args:
        query: Search query. Web-search syntax: bare words, "quoted
            phrases", ``or``, and a leading ``-`` to exclude.
        limit: Maximum results to return
        offset: Skip first N results (for pagination)
        db: Database connection (uses singleton if not provided)

    Returns:
        SearchResult with matching works

    Example:
        >>> results = search("machine learning neural networks")
        >>> print(f"Found {results.total} matches in {results.elapsed_ms:.1f}ms")
    """
    if db is None:
        db = get_db()

    start = _time.perf_counter()

    # Get total count
    count_row = db.fetchone(
        f"SELECT COUNT(*) as total FROM works WHERE {_MATCH}",
        (TEXT_SEARCH_CONFIG, query),
    )
    total = count_row["total"] if count_row else 0

    # Get matching works. ORDER BY is not decoration: LIMIT/OFFSET without one
    # is free to return a row on two consecutive pages and omit another
    # entirely, so paginating an unordered query loses results silently.
    rows = db.fetchall(
        f"""
        SELECT *
        FROM works
        WHERE {_MATCH}
        ORDER BY id
        LIMIT %s OFFSET %s
        """,
        (TEXT_SEARCH_CONFIG, query, limit, offset),
    )

    elapsed_ms = (_time.perf_counter() - start) * 1000

    # Convert to Work objects
    works = []
    for row in rows:
        data = db._row_to_dict(row)
        works.append(Work.from_db_row(data))

    return SearchResult(
        works=works,
        total=total,
        query=query,
        elapsed_ms=elapsed_ms,
    )


def count(query: str, db: Optional[Database] = None) -> int:
    """
    Count matching works without fetching results.

    Args:
        query: Search query
        db: Database connection

    Returns:
        Number of matching works
    """
    if db is None:
        db = get_db()

    row = db.fetchone(
        f"SELECT COUNT(*) as total FROM works WHERE {_MATCH}",
        (TEXT_SEARCH_CONFIG, query),
    )
    return row["total"] if row else 0


def search_ids(
    query: str,
    limit: int = 1000,
    db: Optional[Database] = None,
) -> List[str]:
    """
    Search and return only OpenAlex IDs (faster than full search).

    Args:
        query: Search query
        limit: Maximum IDs to return
        db: Database connection

    Returns:
        List of matching OpenAlex IDs
    """
    if db is None:
        db = get_db()

    rows = db.fetchall(
        f"""
        SELECT openalex_id
        FROM works
        WHERE {_MATCH}
        ORDER BY id
        LIMIT %s
        """,
        (TEXT_SEARCH_CONFIG, query, limit),
    )

    return [row["openalex_id"] for row in rows]


def _search_with_db(db: Database, query: str, limit: int, offset: int) -> SearchResult:
    """Search with explicit database connection (for thread-safe async)."""
    return search(query, limit, offset, db=db)


def _count_with_db(db: Database, query: str) -> int:
    """Count with explicit database connection (for thread-safe async)."""
    return count(query, db=db)

# EOF
