#!/usr/bin/env python3
# Timestamp: 2026-08-30
"""Build indexes required for fast Impact Factor calculation.

This script creates the indexes needed for efficient IF calculation:
- Works table: issn, issn+year composite, source_id
- Citations table: verifies existing indexes

Run this AFTER 05_build_citations_table.py completes.

Usage:
    python 06_build_if_indexes.py [--dsn DSN]

Example:
    python scripts/database/06_build_if_indexes.py
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, resolve_dsn  # noqa: E402

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# Indexes for IF calculation
IF_INDEXES = [
    # Works table indexes
    {
        "name": "idx_works_issn",
        "table": "works",
        "sql": "CREATE INDEX IF NOT EXISTS idx_works_issn ON works(issn)",
        "purpose": "Fast ISSN lookup for journal identification",
    },
    {
        "name": "idx_works_issn_year",
        "table": "works",
        "sql": "CREATE INDEX IF NOT EXISTS idx_works_issn_year ON works(issn, year)",
        "purpose": "KEY: Find all works by journal in year range (IF denominator)",
    },
    {
        "name": "idx_works_source_id",
        "table": "works",
        "sql": "CREATE INDEX IF NOT EXISTS idx_works_source_id ON works(source_id)",
        "purpose": "Alternative journal lookup by OpenAlex source ID",
    },
    {
        "name": "idx_works_source_id_year",
        "table": "works",
        "sql": "CREATE INDEX IF NOT EXISTS idx_works_source_id_year ON works(source_id, year)",
        "purpose": "Find works by source_id + year (alternative to ISSN)",
    },
]

# Citation indexes (verify they exist)
CITATION_INDEXES = [
    {
        "name": "idx_citations_cited_year",
        "table": "citations",
        "sql": "CREATE INDEX IF NOT EXISTS idx_citations_cited_year ON citations(cited_id, citing_year)",
        "purpose": "KEY: Find citations TO a work IN a specific year (IF numerator)",
    },
    {
        "name": "idx_citations_citing",
        "table": "citations",
        "sql": "CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_id)",
        "purpose": "Find all references FROM a work (forward citation graph)",
    },
    {
        "name": "idx_citations_year",
        "table": "citations",
        "sql": "CREATE INDEX IF NOT EXISTS idx_citations_year ON citations(citing_year)",
        "purpose": "Year-based aggregations and trends",
    },
]


def relation_exists(conn, name: str) -> bool:
    """Whether ``name`` resolves to a relation this role can see.

    ``to_regclass`` covers indexes as well as tables — both live in the same
    namespace — so one helper answers both questions here.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
        return bool(cursor.fetchone()[0])


def create_index(conn, index_info: dict) -> float:
    """Create an index and return time taken in minutes."""
    name = index_info["name"]
    sql = index_info["sql"]
    purpose = index_info["purpose"]

    if relation_exists(conn, name):
        logger.info(f"  [ok] {name} already exists")
        return 0.0

    logger.info(f"  Creating {name}...")
    logger.info(f"    Purpose: {purpose}")

    start = time.time()
    with conn.cursor() as cursor:
        cursor.execute(sql)
    conn.commit()
    elapsed = (time.time() - start) / 60

    logger.info(f"    Done in {elapsed:.1f} minutes")
    return elapsed


def build_if_indexes(dsn: str) -> None:
    """Build all indexes needed for IF calculation."""
    logger.info(f"Building IF indexes in: {dsn}")

    conn = connect(dsn)

    if not relation_exists(conn, "works"):
        logger.error("No works table. Run 02_build_database.py first!")
        conn.close()
        sys.exit(1)

    total_time = 0.0

    has_citations = relation_exists(conn, "citations")

    if not has_citations:
        logger.warning("Citations table not found!")
        logger.warning("Run: python scripts/database/05_build_citations_table.py first")

    # Build works indexes
    logger.info("")
    logger.info("=" * 60)
    logger.info("WORKS TABLE INDEXES (for finding journal articles by ISSN/year)")
    logger.info("=" * 60)

    for idx in IF_INDEXES:
        total_time += create_index(conn, idx)

    # Build/verify citations indexes
    if has_citations:
        logger.info("")
        logger.info("=" * 60)
        logger.info("CITATIONS TABLE INDEXES (for counting citations by year)")
        logger.info("=" * 60)

        for idx in CITATION_INDEXES:
            total_time += create_index(conn, idx)

    # Run ANALYZE
    logger.info("")
    logger.info("Running ANALYZE for query optimization...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE works")
        if has_citations:
            cursor.execute("ANALYZE citations")
    conn.commit()
    conn.close()

    from openalex_local._core.state import set_metadata

    set_metadata("if_indexes_completed", time.strftime("%Y-%m-%d %H:%M:%S"))

    logger.info("")
    logger.info("=" * 60)
    logger.info("IF INDEXES BUILD COMPLETE")
    logger.info(f"Total time: {total_time:.1f} minutes")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Impact Factor calculation is now available:")
    logger.info("  openalex-local search 'query' -if")


def main():
    parser = argparse.ArgumentParser(
        description="Build indexes for Impact Factor calculation"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )

    args = parser.parse_args()
    build_if_indexes(resolve_dsn(args.dsn))


if __name__ == "__main__":
    main()
