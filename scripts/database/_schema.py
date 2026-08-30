#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: scripts/database/_schema.py
"""The corpus schema, declared once.

Every build step and the test-corpus builder read their DDL from here. They
used to each carry their own copy, which is how ``works.is_oa`` came to be an
integer in one file and a flag in another, and how the test corpus ended up
without the columns the real one has — a suite that passes against a schema
nothing else builds is measuring its own fixture.

POSTGRESQL, AND ONLY POSTGRESQL. There is no engine parameter here and no
dialect switch. The address of the server is not this module's business
either: :func:`scitex_dev.store.host_store` resolves that, and a build script
asks it rather than accepting a path.

FULL-TEXT SEARCH IS A COLUMN, NOT A TABLE
-----------------------------------------
``works.search_vector`` is a ``tsvector`` covered by a GIN index. The previous
design kept the index in a separate table joined on a row identifier the
corpus did not declare as a column, so any rebuild that renumbered ``works``
made every hit point at the wrong row — silently, because the join still
succeeded. A column cannot drift from the row it belongs to.
"""

from __future__ import annotations

__all__ = [
    "ALL_DDL",
    "CITATIONS_DDL",
    "CITATIONS_INDEXES_DDL",
    "FTS_CONFIG",
    "FTS_INDEX_DDL",
    "IF_DDL",
    "SOURCES_DDL",
    "WORKS_COLUMNS",
    "WORKS_DDL",
    "WORKS_INDEXES_DDL",
    "search_vector_expression",
]

#: The text-search configuration the index is built with. Query-time parsing
#: MUST name the same one, or a search stems its words differently from the
#: index and misses rows that are present.
FTS_CONFIG = "english"


def search_vector_expression(title: str = "title", abstract: str = "abstract") -> str:
    """The expression that fills ``works.search_vector``.

    Exposed as a function so the builder, the incremental updater and the
    test-corpus builder cannot disagree about how a row is indexed.
    """
    return (
        f"to_tsvector('{FTS_CONFIG}', "
        f"coalesce({title}, '') || ' ' || coalesce({abstract}, ''))"
    )


#: The columns a work record is written with, in the order the INSERT uses.
#: Kept as data so a writer can build its statement from it instead of
#: repeating twenty-six names and getting one of them out of order.
WORKS_COLUMNS = (
    "openalex_id",
    "doi",
    "title",
    "abstract",
    "year",
    "publication_date",
    "type",
    "language",
    "source",
    "source_id",
    "issn",
    "volume",
    "issue",
    "first_page",
    "last_page",
    "publisher",
    "cited_by_count",
    "is_oa",
    "oa_status",
    "oa_url",
    "authors_json",
    "concepts_json",
    "topics_json",
    "referenced_works_json",
    "ref_count",
    "raw_json",
)

WORKS_DDL = """
-- Works table: core metadata for each scholarly work
CREATE TABLE IF NOT EXISTS works (
    id BIGSERIAL PRIMARY KEY,
    openalex_id TEXT UNIQUE NOT NULL,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    publication_date TEXT,
    type TEXT,
    language TEXT,
    source TEXT,
    source_id TEXT,
    issn TEXT,
    volume TEXT,
    issue TEXT,
    first_page TEXT,
    last_page TEXT,
    publisher TEXT,
    cited_by_count INTEGER DEFAULT 0,
    is_oa BOOLEAN DEFAULT FALSE,
    oa_status TEXT,
    oa_url TEXT,
    authors_json TEXT,
    concepts_json TEXT,
    topics_json TEXT,
    referenced_works_json TEXT,
    -- Reference count, precomputed. Named ref_count because script 07 and
    -- the two indexes it builds already use that name; a second spelling
    -- of one fact is how a filter comes to read the column nobody fills.
    ref_count INTEGER,
    raw_json TEXT,
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

WORKS_INDEXES_DDL = """
-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_works_doi ON works(doi);
CREATE INDEX IF NOT EXISTS idx_works_year ON works(year);
CREATE INDEX IF NOT EXISTS idx_works_source ON works(source);
CREATE INDEX IF NOT EXISTS idx_works_type ON works(type);
CREATE INDEX IF NOT EXISTS idx_works_language ON works(language);
CREATE INDEX IF NOT EXISTS idx_works_cited_by_count ON works(cited_by_count);
CREATE INDEX IF NOT EXISTS idx_works_is_oa ON works(is_oa);
"""

#: GIN, not the default B-tree: a B-tree cannot answer ``@@`` at all, and the
#: index would be built, reported as present, and never used by a single
#: search.
FTS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_works_search_vector
    ON works USING GIN (search_vector);
"""

SOURCES_DDL = """
-- Sources table: journal/venue metadata with impact metrics
CREATE TABLE IF NOT EXISTS sources (
    id BIGSERIAL PRIMARY KEY,
    openalex_id TEXT UNIQUE NOT NULL,
    issn_l TEXT,
    issns TEXT,  -- JSON array of all ISSNs
    display_name TEXT,
    display_name_lower TEXT,  -- For case-insensitive search
    type TEXT,  -- journal, repository, conference, etc.
    host_organization TEXT,
    country_code TEXT,
    homepage_url TEXT,

    -- Bibliometrics
    works_count INTEGER DEFAULT 0,
    oa_works_count INTEGER DEFAULT 0,
    cited_by_count INTEGER DEFAULT 0,

    -- Impact metrics (from summary_stats)
    two_year_mean_citedness DOUBLE PRECISION,  -- Impact Factor equivalent
    h_index INTEGER,
    i10_index INTEGER,

    -- OA status
    is_oa BOOLEAN DEFAULT FALSE,
    is_in_doaj BOOLEAN DEFAULT FALSE,
    is_core BOOLEAN DEFAULT FALSE,

    -- Temporal info
    first_publication_year INTEGER,
    last_publication_year INTEGER,

    -- APC
    apc_usd INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ISSN lookup table for fast journal lookup by ISSN
CREATE TABLE IF NOT EXISTS issn_lookup (
    issn TEXT PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES sources(id)
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_sources_issn_l ON sources(issn_l);
CREATE INDEX IF NOT EXISTS idx_sources_display_name_lower ON sources(display_name_lower);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(type);
CREATE INDEX IF NOT EXISTS idx_sources_two_year_mean_citedness ON sources(two_year_mean_citedness);
CREATE INDEX IF NOT EXISTS idx_sources_h_index ON sources(h_index);
CREATE INDEX IF NOT EXISTS idx_sources_cited_by_count ON sources(cited_by_count);
CREATE INDEX IF NOT EXISTS idx_sources_works_count ON sources(works_count);
"""

CITATIONS_DDL = """
-- Citations table: tracks which works cite which other works
-- Used for accurate impact factor calculation
CREATE TABLE IF NOT EXISTS citations (
    citing_id TEXT NOT NULL,      -- OpenAlex ID of citing work (e.g., W1234567890)
    cited_id TEXT NOT NULL,       -- OpenAlex ID of cited work
    citing_year INTEGER NOT NULL  -- Year when the citation occurred
);
"""

CITATIONS_INDEXES_DDL = """
-- Index for finding all citations TO a work in a specific year (for IF calculation)
CREATE INDEX IF NOT EXISTS idx_citations_cited_year ON citations(cited_id, citing_year);

-- Index for finding all citations FROM a work
CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_id);

-- Index for year-based queries
CREATE INDEX IF NOT EXISTS idx_citations_year ON citations(citing_year);
"""

IF_DDL = """
-- Precomputed Impact Factors (JCR-style calculation)
CREATE TABLE IF NOT EXISTS journal_impact_factors (
    issn TEXT NOT NULL,
    journal_name TEXT,
    year INTEGER NOT NULL,
    window INTEGER DEFAULT 2,          -- 2-year or 5-year window
    impact_factor DOUBLE PRECISION,    -- Calculated IF (rounded to 1 decimal)
    citations_count INTEGER,           -- Numerator: citations to articles in window
    articles_count INTEGER,            -- Denominator: citable articles in window
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (issn, year, window)
);

-- Index for fast ISSN lookup
CREATE INDEX IF NOT EXISTS idx_jif_issn ON journal_impact_factors(issn);
CREATE INDEX IF NOT EXISTS idx_jif_year ON journal_impact_factors(year);
CREATE INDEX IF NOT EXISTS idx_jif_if ON journal_impact_factors(impact_factor);
"""

#: Everything, in dependency order. ``issn_lookup`` references ``sources``, so
#: the order is not cosmetic.
ALL_DDL = (
    WORKS_DDL
    + WORKS_INDEXES_DDL
    + FTS_INDEX_DDL
    + SOURCES_DDL
    + CITATIONS_DDL
    + CITATIONS_INDEXES_DDL
    + IF_DDL
)

# EOF
