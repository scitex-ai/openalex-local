"""Main API for openalex_local.

Supports two modes:
- db: Direct corpus access (requires a reachable, populated corpus)
- http: HTTP API access (requires API server)

Mode is auto-detected or can be set explicitly via:
- OPENALEX_LOCAL_MODE environment variable ("db" or "http")
- OPENALEX_LOCAL_API_URL environment variable (API URL)
- configure() or configure_http() functions

Where the corpus lives is resolved by ``scitex_dev.store.host_store`` and is
moved with ``SCITEX_STORE_DSN``; this package holds no second answer.
"""

from typing import List, Optional

from . import fts
from .config import Config
from .db import close_db, get_db
from .models import SearchResult, Work

__all__ = [
    # Core functions
    "search",
    "count",
    "get",
    "get_many",
    "exists",
    "info",
    # Enrich functions
    "enrich",
    "enrich_ids",
    # Configuration
    "configure",
    "get_mode",
    # Models (public)
    "Work",
    "SearchResult",
]


def _get_http_client():
    """Get HTTP client (lazy import to avoid circular dependency)."""
    from .._remote import RemoteClient

    return RemoteClient(Config.get_api_url())


def search(
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> SearchResult:
    """
    Full-text search across works.

    Uses the corpus full-text index over titles and abstracts.

    Args:
        query: Search query (web-search syntax: bare words, "quoted
            phrases", ``or``, leading ``-`` to exclude)
        limit: Maximum results to return
        offset: Skip first N results (for pagination)

    Returns:
        SearchResult with matching works

    Example:
        >>> from openalex_local import search
        >>> results = search("machine learning")
        >>> print(f"Found {results.total} matches")
    """
    if Config.get_mode() == "http":
        client = _get_http_client()
        return client.search(query=query, limit=limit, offset=offset)
    return fts.search(query, limit, offset)


def count(query: str) -> int:
    """
    Count matching works without fetching results.

    Args:
        query: Full-text search query

    Returns:
        Number of matching works
    """
    if Config.get_mode() == "http":
        client = _get_http_client()
        result = client.search(query=query, limit=1)
        return result.total
    return fts.count(query)


def get(id_or_doi: str) -> Optional[Work]:
    """
    Get a work by OpenAlex ID or DOI.

    Args:
        id_or_doi: OpenAlex ID (e.g., W2741809807) or DOI

    Returns:
        Work object or None if not found

    Example:
        >>> from openalex_local import get
        >>> work = get("W2741809807")
        >>> work = get("10.1038/nature12373")
        >>> print(work.title)
    """
    if Config.get_mode() == "http":
        client = _get_http_client()
        return client.get(id_or_doi)

    db = get_db()

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


def get_many(ids: List[str]) -> List[Work]:
    """
    Get multiple works by OpenAlex ID or DOI.

    Args:
        ids: List of OpenAlex IDs or DOIs

    Returns:
        List of Work objects (missing IDs are skipped)
    """
    if Config.get_mode() == "http":
        client = _get_http_client()
        return client.get_many(ids)

    works = []
    for id_or_doi in ids:
        work = get(id_or_doi)
        if work:
            works.append(work)
    return works


def exists(id_or_doi: str) -> bool:
    """
    Check if a work exists in the database.

    Args:
        id_or_doi: OpenAlex ID or DOI

    Returns:
        True if work exists
    """
    if Config.get_mode() == "http":
        client = _get_http_client()
        return client.exists(id_or_doi)

    db = get_db()

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


def configure(dsn: str) -> None:
    """
    Configure for direct corpus access at an explicit address.

    Only needed to reach a corpus OTHER than the one this host resolves to.
    Leave it alone and ``scitex_dev.store.host_store`` decides, which is what
    ``SCITEX_STORE_DSN`` is for.

    Args:
        dsn: PostgreSQL connection string for the corpus

    Example:
        >>> from openalex_local import configure
        >>> configure("postgresql://reader@scitex-primary:55432/scitex")
    """
    Config.set_dsn(dsn)
    close_db()


def configure_http(api_url: str = "http://localhost:31292") -> None:
    """
    Configure for HTTP API access.

    Args:
        api_url: URL of OpenAlex Local API server

    Example:
        >>> from openalex_local import configure_http
        >>> configure_http("http://localhost:31292")
    """
    Config.set_api_url(api_url)


def get_mode() -> str:
    """
    Get current mode.

    Returns:
        "db" or "http"
    """
    return Config.get_mode()


def info() -> dict:
    """
    Get database/API information.

    Returns:
        Dictionary with database stats and mode info

    Raises:
        FileNotFoundError: If no database configured and HTTP mode unavailable
    """
    mode = Config.get_mode()

    if mode == "http":
        client = _get_http_client()
        http_info = client.info()
        return {"mode": "http", "status": "ok", **http_info}

    # DB mode - raises if the corpus cannot be opened
    db = get_db()

    # The recorded counters first. They come from the build steps and cost one
    # lookup; COUNT(*) over 284M rows is a table scan and would make `info()`
    # unusable on a full corpus. Falling back to MAX(id) is an approximation
    # and is labelled as one below.
    work_count = _recorded_int("total_works")
    if work_count == 0:
        try:
            row = db.fetchone("SELECT MAX(id) as count FROM works")
            work_count = (row["count"] or 0) if row else 0
        except Exception:
            work_count = 0

    fts_count = _recorded_int("fts_total_indexed")
    if fts_count == 0:
        try:
            row = db.fetchone(
                "SELECT COUNT(*) as count FROM works WHERE search_vector IS NOT NULL"
            )
            fts_count = (row["count"] or 0) if row else 0
        except Exception:
            fts_count = 0

    # Sources table is optional (requires build step 04)
    sources_count = 0
    has_sources = False
    try:
        if db.has_sources_table():
            has_sources = True
            row = db.fetchone("SELECT COUNT(*) as count FROM sources")
            sources_count = (row["count"] or 0) if row else 0
    except Exception:
        pass  # sources table not built yet

    return {
        "status": "ok",
        "mode": "db",
        "dsn": db.dsn,
        "work_count": work_count,
        "fts_indexed": fts_count,
        "has_sources": has_sources,
        "sources_count": sources_count,
    }


def _recorded_int(key: str) -> int:
    """A counter the build steps recorded, or 0 when none was.

    Zero rather than None so the caller's "fall back to a live query" branch
    is one comparison. A store that is unreachable is also 0 here — the live
    query then answers, and if that fails too the caller reports 0 rather
    than raising in a status call.
    """
    from .state import get_metadata

    try:
        recorded = get_metadata(key)
    except Exception:
        return 0
    try:
        return int(recorded) if recorded else 0
    except (TypeError, ValueError):
        return 0


def enrich(
    results: SearchResult,
    include_abstract: bool = True,
    include_concepts: bool = True,
) -> SearchResult:
    """
    Enrich search results with full metadata.

    This function re-fetches works from the database to ensure all fields
    are populated, including abstract and concepts which may be truncated
    in search results.

    Args:
        results: SearchResult from a search query
        include_abstract: Include full abstract text (default True)
        include_concepts: Include concept/topic data (default True)

    Returns:
        SearchResult with enriched Work objects

    Example:
        >>> results = search("machine learning", limit=10)
        >>> enriched = enrich(results)
        >>> for work in enriched:
        ...     print(work.abstract)  # Full abstract available
    """
    if not results.works:
        return results

    # Get full work data for each work
    ids = [w.openalex_id for w in results.works]
    enriched_works = get_many(ids)

    # If concepts/abstract not wanted, clear them
    if not include_abstract:
        for work in enriched_works:
            work.abstract = None
    if not include_concepts:
        for work in enriched_works:
            work.concepts = []
            work.topics = []

    return SearchResult(
        works=enriched_works,
        total=results.total,
        query=results.query,
        elapsed_ms=results.elapsed_ms,
    )


def enrich_ids(
    ids: List[str],
    include_abstract: bool = True,
    include_concepts: bool = True,
) -> List[Work]:
    """
    Enrich a list of OpenAlex IDs or DOIs with full metadata.

    Args:
        ids: List of OpenAlex IDs (e.g., W2741809807) or DOIs
        include_abstract: Include full abstract text (default True)
        include_concepts: Include concept/topic data (default True)

    Returns:
        List of Work objects with full metadata

    Example:
        >>> ids = ["W2741809807", "10.1038/nature12373"]
        >>> works = enrich_ids(ids)
        >>> for work in works:
        ...     print(f"{work.title}: {work.cited_by_count} citations")
    """
    works = get_many(ids)

    if not include_abstract:
        for work in works:
            work.abstract = None
    if not include_concepts:
        for work in works:
            work.concepts = []
            work.topics = []

    return works
