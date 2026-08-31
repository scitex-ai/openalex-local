#!/usr/bin/env python3
"""Populate ``works.ref_count`` and index it, for citable-items filtering.

The column itself is now part of the corpus schema (``_schema.WORKS_DDL``), so
this step no longer adds it — it fills the rows that predate the loader writing
it and builds the two indexes a JCR-style IF calculation needs (which filters
on >20 references).

Usage:
    python 07_add_ref_count_column.py [--dsn DSN]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, resolve_dsn  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def relation_exists(conn, name: str) -> bool:
    """Whether ``name`` resolves to a relation this role can see."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
        return bool(cursor.fetchone()[0])


def add_ref_count_column(dsn: str, batch_size: int = 100000) -> None:
    """Populate ref_count on the works table and index it."""
    logger.info(f"Populating ref_count in: {dsn}")

    conn = connect(dsn)

    if not relation_exists(conn, "works"):
        logger.error("No works table. Run 02_build_database.py first!")
        conn.close()
        sys.exit(1)

    # The column belongs to the schema now. This is still here because a corpus
    # built before it was added has the rows but not the column, and refusing to
    # start would be the wrong answer for exactly the corpus this step exists to
    # repair.
    with conn.cursor() as cursor:
        cursor.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS ref_count INTEGER")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM works "
            "WHERE ref_count IS NULL AND referenced_works_json IS NOT NULL"
        )
        unpopulated = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM works WHERE referenced_works_json IS NOT NULL"
        )
        total_with_refs = cursor.fetchone()[0]

    logger.info(f"Works with refs: {total_with_refs:,}")
    logger.info(f"Needs population: {unpopulated:,}")

    if unpopulated == 0:
        logger.info("All ref_count values already populated")
    else:
        logger.info("Populating ref_count values...")
        start_time = time.time()

        # Walk by primary key, and let the UPDATE tell us where it got to.
        # Counting batches instead would drift from the rows actually visited
        # the moment one batch matched fewer rows than its width.
        update_sql = """
            UPDATE works
            SET ref_count = json_array_length(referenced_works_json::json)
            WHERE id IN (
                SELECT id FROM works
                WHERE id > %s
                  AND ref_count IS NULL
                  AND referenced_works_json IS NOT NULL
                ORDER BY id
                LIMIT %s
            )
            RETURNING id
        """

        last_id = 0
        processed = 0
        while True:
            with conn.cursor() as cursor:
                cursor.execute(update_sql, (last_id, batch_size))
                ids = [row[0] for row in cursor.fetchall()]
            conn.commit()

            if not ids:
                break

            processed += len(ids)
            last_id = max(ids)

            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            pct = 100 * processed / unpopulated if unpopulated else 100.0
            logger.info(
                f"Progress: {processed:,}/{unpopulated:,} ({pct:.1f}%) | "
                f"Rate: {rate:.0f}/s"
            )

        elapsed = time.time() - start_time
        logger.info(f"Population completed in {elapsed / 60:.1f} minutes")

    # Create index
    logger.info("Creating index on ref_count...")
    if relation_exists(conn, "idx_works_ref_count"):
        logger.info("Index idx_works_ref_count already exists")
    else:
        start_time = time.time()
        with conn.cursor() as cursor:
            cursor.execute("CREATE INDEX idx_works_ref_count ON works(ref_count)")
        conn.commit()
        logger.info(f"Index created in {(time.time() - start_time) / 60:.1f} minutes")

    # Create composite index for IF calculation: (issn, year, ref_count)
    logger.info("Creating composite index for IF calculation...")
    if relation_exists(conn, "idx_works_issn_year_refcount"):
        logger.info("Index idx_works_issn_year_refcount already exists")
    else:
        start_time = time.time()
        with conn.cursor() as cursor:
            cursor.execute(
                "CREATE INDEX idx_works_issn_year_refcount "
                "ON works(issn, year, ref_count)"
            )
        conn.commit()
        logger.info(
            f"Composite index created in {(time.time() - start_time) / 60:.1f} minutes"
        )

    # Analyze
    logger.info("Running ANALYZE...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE works")
    conn.commit()

    # Stats
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM works WHERE ref_count > 20")
        citable = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM works")
        total = cursor.fetchone()[0]

    logger.info("=" * 60)
    logger.info("COMPLETED")
    logger.info(f"Total works: {total:,}")
    if total:
        logger.info(
            f"Citable items (>20 refs): {citable:,} ({100 * citable / total:.1f}%)"
        )
    logger.info("=" * 60)

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Populate ref_count for fast IF calculation"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100000,
        help="Batch size for updates (default: 100000)",
    )

    args = parser.parse_args()

    add_ref_count_column(resolve_dsn(args.dsn), args.batch_size)


if __name__ == "__main__":
    main()
