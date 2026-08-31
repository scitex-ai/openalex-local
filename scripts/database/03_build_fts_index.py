#!/usr/bin/env python3
# Timestamp: 2026-08-30
"""Build the corpus full-text index.

Fills ``works.search_vector`` and creates the GIN index over it.

THE INDEX IS A COLUMN NOW, NOT A SEPARATE TABLE. The previous design kept a
shadow table keyed on the corpus's internal row number, plus three triggers to
hold the two in sync. A column cannot fall out of sync with the row it belongs
to, so both the shadow table and the triggers are gone rather than translated.

Usage:
    python 03_build_fts_index.py [--dsn DSN] [--batch-size N] [--rebuild]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, resolve_dsn  # noqa: E402
from _schema import FTS_CONFIG, FTS_INDEX_DDL, search_vector_expression  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_total_works(conn) -> int:
    """Get total number of works in the corpus."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM works")
        return cursor.fetchone()[0]


def get_indexed_count(conn) -> int:
    """Get the number of works whose search vector is populated."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM works WHERE search_vector IS NOT NULL")
        return cursor.fetchone()[0]


def _corpus_present(conn) -> bool:
    """Whether the works table exists at all."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('works') IS NOT NULL")
        return bool(cursor.fetchone()[0])


def build_fts_index(
    dsn: str,
    batch_size: int = 50000,
    rebuild: bool = False,
) -> None:
    """Build the full-text index."""
    logger.info(f"Building full-text index for: {dsn}")

    conn = connect(dsn)

    if not _corpus_present(conn):
        logger.error("No works table. Run 02_build_database.py first!")
        conn.close()
        sys.exit(1)

    total_works = get_total_works(conn)
    logger.info(f"Total works in corpus: {total_works:,}")

    if total_works == 0:
        logger.error("No works in the corpus! Run 02_build_database.py first.")
        conn.close()
        sys.exit(1)

    indexed = get_indexed_count(conn)
    if indexed > 0 and not rebuild:
        logger.info(f"Full-text index already covers {indexed:,} works")
        if indexed >= total_works * 0.99:  # Allow 1% tolerance
            logger.info("Index appears complete. Use --rebuild to force a rebuild.")
            conn.close()
            return
        logger.info("Index incomplete. Continuing with the remaining rows...")

    if rebuild:
        logger.info("Clearing existing search vectors...")
        with conn.cursor() as cursor:
            cursor.execute("UPDATE works SET search_vector = NULL")
        conn.commit()

    # Populate in id-ordered batches. The cursor is the last id VISITED, not a
    # count: a plain OFFSET would re-scan the rows already done on every batch,
    # which turns a linear job into a quadratic one at 284M rows.
    logger.info(f"Populating search vectors (batch size: {batch_size:,})...")
    start_time = time.time()

    expression = search_vector_expression()
    update_sql = f"""
        UPDATE works
        SET search_vector = {expression}
        WHERE id IN (
            SELECT id FROM works
            WHERE id > %s AND search_vector IS NULL
            ORDER BY id
            LIMIT %s
        )
        RETURNING id
    """

    last_id = 0
    total_updated = 0

    while True:
        batch_start = time.time()
        with conn.cursor() as cursor:
            cursor.execute(update_sql, (last_id, batch_size))
            ids = [row[0] for row in cursor.fetchall()]
        conn.commit()

        if not ids:
            break

        total_updated += len(ids)
        last_id = max(ids)

        batch_elapsed = time.time() - batch_start
        elapsed = time.time() - start_time
        rate = total_updated / elapsed if elapsed > 0 else 0
        progress = (total_updated / total_works) * 100

        logger.info(
            f"  Progress: {total_updated:,}/{total_works:,} ({progress:.1f}%) | "
            f"Rate: {rate:.0f}/s | "
            f"Batch: {batch_elapsed:.1f}s"
        )

    # The GIN index is created AFTER the column is filled: building it first
    # would pay the maintenance cost on every one of those updates.
    logger.info("Creating the GIN index over search_vector...")
    with conn.cursor() as cursor:
        cursor.execute(FTS_INDEX_DDL)
    conn.commit()

    elapsed = time.time() - start_time
    final_count = get_indexed_count(conn)

    logger.info("=" * 60)
    logger.info("Full-text index build completed!")
    logger.info(f"Total indexed: {final_count:,}")
    logger.info(f"Total time: {elapsed / 60:.1f} minutes")
    if elapsed > 0:
        logger.info(f"Average rate: {final_count / elapsed:.0f} records/s")

    from openalex_local._core.state import set_metadata

    set_metadata("fts_build_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("fts_total_indexed", str(final_count))

    logger.info("Running ANALYZE so the planner knows about the new index...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE works")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_size_pretty(pg_total_relation_size('works'))")
        size = cursor.fetchone()[0]
    conn.close()
    logger.info(f"works table size: {size}")
    logger.info("Full-text index ready for use!")


def verify_fts(dsn: str) -> None:
    """Verify the full-text index with a test search."""
    logger.info("Verifying the full-text index...")

    conn = connect(dsn, autocommit=True)
    match = f"search_vector @@ websearch_to_tsquery('{FTS_CONFIG}', %s)"

    test_query = "machine learning"
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM works WHERE {match}", (test_query,))
        count = cursor.fetchone()[0]
    logger.info(f"Test search '{test_query}': {count:,} results")

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT openalex_id, title, year
            FROM works
            WHERE {match}
            ORDER BY id
            LIMIT 3
            """,
            (test_query,),
        )
        results = cursor.fetchall()

    if results:
        logger.info("Sample results:")
        for openalex_id, title, year in results:
            title_short = title[:60] + "..." if title and len(title) > 60 else title
            logger.info(f"  [{year}] {openalex_id}: {title_short}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Build the full-text search index for the OpenAlex corpus"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50000,
        help="Batch size for index population (default: 50000)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a rebuild even if the index is already populated",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify the existing index",
    )

    args = parser.parse_args()
    dsn = resolve_dsn(args.dsn)

    if args.verify_only:
        verify_fts(dsn)
    else:
        build_fts_index(
            dsn=dsn,
            batch_size=args.batch_size,
            rebuild=args.rebuild,
        )
        verify_fts(dsn)


if __name__ == "__main__":
    main()
