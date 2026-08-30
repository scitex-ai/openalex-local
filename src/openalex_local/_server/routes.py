"""Work search and retrieval endpoints."""

import time
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from .._core import fts
from .._core.db import get_db
from .._core.models import Work

router = APIRouter(tags=["works"])


# Pydantic models for responses
class WorkResponse(BaseModel):
    """Work metadata response."""

    openalex_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = []
    year: Optional[int] = None
    source: Optional[str] = None
    issn: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    abstract: Optional[str] = None
    cited_by_count: Optional[int] = None
    concepts: List[dict] = []
    topics: List[dict] = []
    is_oa: bool = False
    oa_url: Optional[str] = None


class SearchResponse(BaseModel):
    """Search results response."""

    query: str
    total: int
    returned: int
    elapsed_ms: float
    results: List[WorkResponse]


class BatchRequest(BaseModel):
    """Batch ID lookup request."""

    ids: List[str]


class BatchResponse(BaseModel):
    """Batch ID lookup response."""

    requested: int
    found: int
    results: List[WorkResponse]


def _work_to_response(work: Work) -> WorkResponse:
    """Convert Work to WorkResponse."""
    return WorkResponse(
        openalex_id=work.openalex_id,
        doi=work.doi,
        title=work.title,
        authors=work.authors,
        year=work.year,
        source=work.source,
        issn=work.issn,
        volume=work.volume,
        issue=work.issue,
        pages=work.pages,
        abstract=work.abstract,
        cited_by_count=work.cited_by_count,
        concepts=work.concepts,
        topics=work.topics,
        is_oa=work.is_oa,
        oa_url=work.oa_url,
    )


@router.get("/works", response_model=SearchResponse)
def search_works(
    q: str = Query(..., description="Search query (web-search syntax)"),
    limit: int = Query(20, ge=1, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip first N results"),
):
    """
    Full-text search across works.

    Uses the corpus full-text index over titles and abstracts.
    Web-search syntax: bare words, "exact phrases", `or`, leading `-`.

    Examples:
        /works?q=machine learning
        /works?q="neural network" AND hippocampus
        /works?q=CRISPR&limit=20
    """
    start = time.perf_counter()

    try:
        results = fts.search(q, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search error: {e}")

    elapsed_ms = (time.perf_counter() - start) * 1000

    return SearchResponse(
        query=q,
        total=results.total,
        returned=len(results.works),
        elapsed_ms=round(elapsed_ms, 2),
        results=[_work_to_response(w) for w in results.works],
    )


@router.get("/works/{id_or_doi:path}", response_model=Optional[WorkResponse])
def get_work(id_or_doi: str):
    """
    Get work metadata by OpenAlex ID or DOI.

    Examples:
        /works/W2741809807
        /works/10.1038/nature12373
    """
    db = get_db()

    # Try as OpenAlex ID first
    if id_or_doi.upper().startswith("W"):
        data = db.get_work(id_or_doi.upper())
        if data:
            work = Work.from_db_row(data)
            return _work_to_response(work)

    # Try as DOI
    data = db.get_work_by_doi(id_or_doi)
    if data:
        work = Work.from_db_row(data)
        return _work_to_response(work)

    raise HTTPException(status_code=404, detail=f"Not found: {id_or_doi}")


@router.post("/works/batch", response_model=BatchResponse)
def get_works_batch(request: BatchRequest):
    """
    Get multiple works by OpenAlex ID or DOI.

    Request body: {"ids": ["W2741809807", "10.1038/..."]}
    """
    db = get_db()
    results = []

    for id_or_doi in request.ids:
        data = None

        # Try as OpenAlex ID first
        if id_or_doi.upper().startswith("W"):
            data = db.get_work(id_or_doi.upper())

        # Try as DOI
        if not data:
            data = db.get_work_by_doi(id_or_doi)

        if data:
            work = Work.from_db_row(data)
            results.append(_work_to_response(work))

    return BatchResponse(
        requested=len(request.ids),
        found=len(results),
        results=results,
    )
