#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: scripts/database/_build_helpers.py
"""Shared helpers for OpenAlex corpus build and update scripts.

Two kinds of thing live here: the parsers that turn a snapshot record into a
row, and the one function every build step uses to reach the corpus.

THE ADDRESS IS NOT AN ARGUMENT. ``resolve_dsn`` asks
:func:`scitex_dev.store.host_store`, which is the fleet's single resolver, and
every script's ``--dsn`` flag only overrides it for that one run. No script
builds a connection string, and none of them accept a filesystem path any
more: a path selected a private file, and a private file is how two hosts came
to hold two different corpora that both reported success.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

__all__ = [
    "connect",
    "extract_authors",
    "extract_concepts",
    "extract_topics",
    "parse_work",
    "reconstruct_abstract",
    "resolve_dsn",
]


def resolve_dsn(override: Optional[str] = None) -> str:
    """The corpus DSN for this run.

    ``override`` is a command line's ``--dsn``; without one the host store
    decides, which ``SCITEX_STORE_DSN`` moves.
    """
    if override:
        return override
    from scitex_dev.store import host_store

    return host_store(pkg="openalex_local", name="corpus").dsn


def connect(dsn: Optional[str] = None, *, autocommit: bool = False):
    """Open a connection to the corpus.

    ``autocommit=False`` by default because the build steps batch: they insert
    thousands of rows and then commit once, and a per-statement transaction
    would multiply the write cost of a 284M-row build by the number of rows.
    Steps that only run DDL pass ``autocommit=True``.
    """
    import psycopg

    return psycopg.connect(resolve_dsn(dsn), autocommit=autocommit)


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return None
    try:
        words = sorted(
            [(pos, word) for word, positions in inverted_index.items() for pos in positions]
        )
        return " ".join(word for _, word in words)
    except Exception:
        return None


def extract_authors(authorships: List[Dict]) -> List[str]:
    """Extract author names from authorships list."""
    authors = []
    for authorship in authorships or []:
        author = authorship.get("author", {})
        name = author.get("display_name")
        if name:
            authors.append(name)
    return authors


def extract_concepts(concepts: List[Dict], limit: int = 5) -> List[Dict[str, Any]]:
    """Extract top concepts with name and score."""
    return [
        {"name": c.get("display_name"), "score": c.get("score")}
        for c in (concepts or [])[:limit]
    ]


def extract_topics(topics: List[Dict], limit: int = 3) -> List[Dict[str, Any]]:
    """Extract top topics with name and subfield."""
    return [
        {
            "name": t.get("display_name"),
            "subfield": t.get("subfield", {}).get("display_name") if t.get("subfield") else None,
            "field": t.get("field", {}).get("display_name") if t.get("field") else None,
        }
        for t in (topics or [])[:limit]
    ]


def parse_work(data: Dict[str, Any], store_raw: bool = False) -> Dict[str, Any]:
    """Parse OpenAlex work JSON into a corpus record.

    The returned keys are exactly ``_schema.WORKS_COLUMNS`` plus
    ``ref_count``, so a caller can build its INSERT from that
    tuple instead of repeating the column list.
    """
    openalex_id = data.get("id", "").replace("https://openalex.org/", "")

    doi = data.get("doi", "").replace("https://doi.org/", "") if data.get("doi") else None

    primary_location = data.get("primary_location") or {}
    source_info = primary_location.get("source") or {}
    source = source_info.get("display_name")
    source_id = (source_info.get("id") or "").replace("https://openalex.org/", "") if source_info.get("id") else None
    issns = source_info.get("issn") or []
    issn = issns[0] if issns else None
    publisher = source_info.get("host_organization_name")

    biblio = data.get("biblio") or {}
    oa_info = data.get("open_access") or {}

    authors = extract_authors(data.get("authorships", []))
    concepts = extract_concepts(data.get("concepts", []))
    topics = extract_topics(data.get("topics", []))
    referenced_works = [
        r.replace("https://openalex.org/", "") for r in (data.get("referenced_works") or [])
    ]

    return {
        "openalex_id": openalex_id,
        "doi": doi,
        "title": data.get("title") or data.get("display_name"),
        "abstract": reconstruct_abstract(data.get("abstract_inverted_index")),
        "year": data.get("publication_year"),
        "publication_date": data.get("publication_date"),
        "type": data.get("type"),
        "language": data.get("language"),
        "source": source,
        "source_id": source_id,
        "issn": issn,
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "first_page": biblio.get("first_page"),
        "last_page": biblio.get("last_page"),
        "publisher": publisher,
        "cited_by_count": data.get("cited_by_count", 0),
        # A real boolean. It was an int 0/1 for the previous engine, which has
        # no boolean type; writing an int into a `boolean` column now raises
        # rather than coercing, and that is the right time to find out.
        "is_oa": bool(oa_info.get("is_oa")),
        "oa_status": oa_info.get("oa_status"),
        "oa_url": oa_info.get("oa_url"),
        "authors_json": json.dumps(authors) if authors else None,
        "concepts_json": json.dumps(concepts) if concepts else None,
        "topics_json": json.dumps(topics) if topics else None,
        "referenced_works_json": json.dumps(referenced_works) if referenced_works else None,
        "ref_count": len(referenced_works),
        "raw_json": json.dumps(data) if store_raw else None,
    }


# EOF
