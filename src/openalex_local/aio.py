"""Async API for openalex_local.

Provides async versions of all core API functions using thread-local
database connections and asyncio.to_thread() for non-blocking execution.

Example:
    >>> import asyncio
    >>> from openalex_local import aio
    >>>
    >>> async def main():
    ...     results = await aio.search("machine learning", limit=10)
    ...     work = await aio.get("W2741809807")
    ...     print(f"Found {results.total} matches")
    >>>
    >>> asyncio.run(main())
"""

import asyncio
import threading
from typing import Dict, List, Optional

from ._core.db import Database
from ._core.fts import _search_with_db, _count_with_db
from ._core.models import SearchResult, Work

__all__ = [
    "search",
    "search_many",
    "count",
    "count_many",
    "get",
    "get_many",
    "exists",
    "info",
]

# Thread-local storage for database connections
_thread_local = threading.local()


def _get_thread_db() -> Database:
    """Get or create thread-local database connection."""
    if not hasattr(_thread_local, "db"):
        _thread_local.db = Database()
    return _thread_local.db


def _search_sync(query: str, limit: int, offset: int) -> SearchResult:
    """Synchronous search with thread-local database."""
    db = _get_thread_db()
    return _search_with_db(db, query, limit, offset)


def _count_sync(query: str) -> int:
    """Synchronous count with thread-local database."""
    db = _get_thread_db()
    return _count_with_db(db, query)


def _get_sync(id_or_doi: str) -> Optional[Work]:
    """Synchronous get with thread-local database."""
    db = _get_thread_db()

    # Try as OpenAlex ID first
    if id_or_doi.startswith("W") or id_or_doi.startswith("w"):
        data = db.get_work(id_or_doi.upper())
        if data:
            return Work.from_db_row(data)

    # Try as DOI
    data = db.get_work_by_doi(id_or_doi)
    if data:
        return Work.from_db_row(data)

    return None


def _get_many_sync(ids: List[str]) -> List[Work]:
    """Synchronous get_many with thread-local database."""
    works = []
    for id_or_doi in ids:
        work = _get_sync(id_or_doi)
        if work:
            works.append(work)
    return works


def _exists_sync(id_or_doi: str) -> bool:
    """Synchronous exists check with thread-local database."""
    db = _get_thread_db()

    # Try as OpenAlex ID first
    if id_or_doi.startswith("W") or id_or_doi.startswith("w"):
        row = db.fetchone(
            "SELECT 1 FROM works WHERE openalex_id = %s", (id_or_doi.upper(),)
        )
        if row:
            return True

    # Try as DOI
    row = db.fetchone("SELECT 1 FROM works WHERE doi = %s", (id_or_doi,))
    return row is not None


def _info_sync() -> dict:
    """Synchronous info with thread-local database."""
    db = _get_thread_db()

    row = db.fetchone("SELECT COUNT(*) as count FROM works")
    work_count = row["count"] if row else 0

    try:
        row = db.fetchone(
            "SELECT COUNT(*) as count FROM works WHERE search_vector IS NOT NULL"
        )
        fts_count = row["count"] if row else 0
    except Exception:
        fts_count = 0

    return {
        "status": "ok",
        "mode": "db",
        "dsn": db.dsn,
        "work_count": work_count,
        "fts_indexed": fts_count,
    }


async def search(
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> SearchResult:
    """
    Async full-text search across works.

    Args:
        query: Search query (web-search syntax)
        limit: Maximum results to return
        offset: Skip first N results (for pagination)

    Returns:
        SearchResult with matching works

    Example:
        >>> results = await aio.search("machine learning", limit=10)
        >>> print(f"Found {results.total} matches")
    """
    return await asyncio.to_thread(_search_sync, query, limit, offset)


async def count(query: str) -> int:
    """
    Async count of matching works.

    Args:
        query: Full-text search query

    Returns:
        Number of matching works
    """
    return await asyncio.to_thread(_count_sync, query)


async def get(id_or_doi: str) -> Optional[Work]:
    """
    Async get work by OpenAlex ID or DOI.

    Args:
        id_or_doi: OpenAlex ID (e.g., W2741809807) or DOI

    Returns:
        Work object or None if not found

    Example:
        >>> work = await aio.get("W2741809807")
        >>> work = await aio.get("10.1038/nature12373")
    """
    return await asyncio.to_thread(_get_sync, id_or_doi)


async def get_many(ids: List[str]) -> List[Work]:
    """
    Async get multiple works by OpenAlex ID or DOI.

    Args:
        ids: List of OpenAlex IDs or DOIs

    Returns:
        List of Work objects (missing IDs are skipped)
    """
    return await asyncio.to_thread(_get_many_sync, ids)


async def exists(id_or_doi: str) -> bool:
    """
    Async check if a work exists in the database.

    Args:
        id_or_doi: OpenAlex ID or DOI

    Returns:
        True if work exists
    """
    return await asyncio.to_thread(_exists_sync, id_or_doi)


async def info() -> dict:
    """
    Async get database information.

    Returns:
        Dictionary with database stats
    """
    return await asyncio.to_thread(_info_sync)


async def search_many(
    queries: List[str],
    limit: int = 10,
) -> List[SearchResult]:
    """
    Execute multiple searches concurrently.

    Args:
        queries: List of search queries
        limit: Maximum results per query

    Returns:
        List of SearchResult objects

    Example:
        >>> queries = ["machine learning", "neural networks", "deep learning"]
        >>> results = await aio.search_many(queries, limit=5)
        >>> for r in results:
        ...     print(f"{r.query}: {r.total} matches")
    """
    tasks = [search(q, limit=limit) for q in queries]
    return await asyncio.gather(*tasks)


async def count_many(queries: List[str]) -> Dict[str, int]:
    """
    Count matches for multiple queries concurrently.

    Args:
        queries: List of search queries

    Returns:
        Dictionary mapping queries to counts

    Example:
        >>> queries = ["machine learning", "neural networks"]
        >>> counts = await aio.count_many(queries)
        >>> print(counts)
        {'machine learning': 5000, 'neural networks': 3000}
    """
    tasks = [count(q) for q in queries]
    counts = await asyncio.gather(*tasks)
    return dict(zip(queries, counts))
