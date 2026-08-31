#!/usr/bin/env python3
# Timestamp: 2026-08-30
"""Build the citations table from the corpus, for impact-factor calculation.

Extracts citation relationships from the ``referenced_works_json`` field in the
works table and builds an indexed citations table for fast IF calculation.

Usage:
    python 05_build_citations_table.py [--dsn DSN] [--batch-size N]

Example:
    python scripts/database/05_build_citations_table.py
    python scripts/database/05_build_citations_table.py --batch-size 50000
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, resolve_dsn  # noqa: E402
from _schema import CITATIONS_DDL, CITATIONS_INDEXES_DDL  # noqa: E402

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


#: Resume cursor for this step. ``last_work_id`` tracks ``works.id`` — the
#: declared primary key. It used to track the engine's implicit row number,
#: which is not a column, is not stable across a rebuild, and therefore could
#: resume a half-finished scan at the wrong place without anything failing.
PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS _citations_build_progress (
    last_work_id BIGINT PRIMARY KEY,
    records_processed BIGINT,
    citations_inserted BIGINT,
    completed_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def get_last_progress(conn) -> Tuple[int, int, int]:
    """Get last progress checkpoint."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('_citations_build_progress') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return 0, 0, 0
        cursor.execute(
            "SELECT last_work_id, records_processed, citations_inserted "
            "FROM _citations_build_progress ORDER BY last_work_id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return row[0], row[1], row[2]
    return 0, 0, 0


def save_progress(conn, last_work_id: int, records: int, citations: int) -> None:
    """Save progress checkpoint."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO _citations_build_progress "
            "(last_work_id, records_processed, citations_inserted) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (last_work_id) DO UPDATE SET "
            "records_processed = EXCLUDED.records_processed, "
            "citations_inserted = EXCLUDED.citations_inserted, "
            "completed_at = NOW()",
            (last_work_id, records, citations),
        )
    conn.commit()


def build_citations_table(
    dsn: str,
    batch_size: int = 10000,
    commit_interval: int = 100000,
    rebuild: bool = False,
) -> None:
    """Build citations table from works' referenced_works_json field."""
    logger.info(f"Building citations table in: {dsn}")
    logger.info(f"Batch size: {batch_size}, Commit interval: {commit_interval}")

    conn = connect(dsn)

    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('works') IS NOT NULL")
        if not cursor.fetchone()[0]:
            logger.error("No works table. Run 02_build_database.py first!")
            conn.close()
            sys.exit(1)

    # Drop existing tables if rebuild
    if rebuild:
        logger.info("Rebuilding: dropping existing citations table...")
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS citations")
            cursor.execute("DROP TABLE IF EXISTS _citations_build_progress")
        conn.commit()

    # Create schema (without indexes - add after data insertion)
    with conn.cursor() as cursor:
        cursor.execute(CITATIONS_DDL)
        cursor.execute(PROGRESS_DDL)
    conn.commit()

    # Get progress
    last_work_id, total_records, total_citations = get_last_progress(conn)

    if last_work_id > 0:
        logger.info(
            f"Resuming from works.id {last_work_id:,} "
            f"({total_records:,} records, {total_citations:,} citations)"
        )

    with conn.cursor() as cursor:
        cursor.execute("SELECT MAX(id) FROM works")
        max_work_id = cursor.fetchone()[0] or 0
    logger.info(f"Total works to process: {max_work_id:,}")

    remaining = max_work_id - last_work_id
    logger.info(f"Remaining: {remaining:,}")

    if remaining <= 0:
        logger.info("All works already processed!")
        logger.info("Ensuring indexes exist...")
        with conn.cursor() as cursor:
            cursor.execute(CITATIONS_INDEXES_DDL)
        conn.commit()
        conn.close()
        return

    # Process works in batches
    start_time = time.time()
    batch_citations = []

    current_work_id = last_work_id

    while current_work_id < max_work_id:
        batch_start = current_work_id
        batch_end = min(current_work_id + batch_size, max_work_id)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, openalex_id, year, referenced_works_json
                FROM works
                WHERE id > %s AND id <= %s
                AND referenced_works_json IS NOT NULL
                AND referenced_works_json != '[]'
                """,
                (batch_start, batch_end),
            )

            for row in cursor:
                _work_id, citing_id, citing_year, refs_json = row
                total_records += 1

                if not citing_year or not refs_json:
                    continue

                try:
                    referenced_works = json.loads(refs_json)
                    for cited_id in referenced_works:
                        if cited_id:  # Skip empty strings
                            batch_citations.append((citing_id, cited_id, citing_year))
                            total_citations += 1
                except (json.JSONDecodeError, TypeError):
                    continue

        # Advance to batch_end even when this batch held no works with refs.
        current_work_id = batch_end

        # Insert citations when batch is large enough
        if len(batch_citations) >= commit_interval:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO citations (citing_id, cited_id, citing_year) "
                    "VALUES (%s, %s, %s)",
                    batch_citations,
                )
            conn.commit()
            save_progress(conn, current_work_id, total_records, total_citations)

            elapsed = time.time() - start_time
            rate = total_records / elapsed if elapsed > 0 else 0
            pct = 100 * current_work_id / max_work_id
            eta_sec = (max_work_id - current_work_id) / rate if rate > 0 else 0
            eta_hr = eta_sec / 3600

            logger.info(
                f"Progress: {current_work_id:,}/{max_work_id:,} ({pct:.1f}%) | "
                f"Records: {total_records:,} | Citations: {total_citations:,} | "
                f"Rate: {rate:.0f}/s | ETA: {eta_hr:.1f}h"
            )
            batch_citations = []

    # Insert remaining citations
    if batch_citations:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO citations (citing_id, cited_id, citing_year) "
                "VALUES (%s, %s, %s)",
                batch_citations,
            )
        conn.commit()
        save_progress(conn, current_work_id, total_records, total_citations)

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Data insertion completed!")
    logger.info(f"Total records processed: {total_records:,}")
    logger.info(f"Total citations inserted: {total_citations:,}")
    logger.info(f"Time: {elapsed / 3600:.1f} hours")

    # Create indexes
    logger.info("Creating indexes (this may take a while)...")
    index_start = time.time()
    with conn.cursor() as cursor:
        cursor.execute(CITATIONS_INDEXES_DDL)
    conn.commit()
    index_elapsed = time.time() - index_start
    logger.info(f"Indexes created in {index_elapsed / 60:.1f} minutes")

    from openalex_local._core.state import set_metadata

    set_metadata("citations_build_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("total_citations", str(total_citations))

    # Analyze for query optimization
    logger.info("Running ANALYZE...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE citations")
    conn.commit()

    conn.close()

    total_elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Citations table build completed!")
    logger.info(f"Total time: {total_elapsed / 3600:.1f} hours")


def main():
    parser = argparse.ArgumentParser(
        description="Build citations table from OpenAlex works"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Batch size for reading works (default: 10000)",
    )
    parser.add_argument(
        "--commit-interval",
        type=int,
        default=100000,
        help="Commit after this many citations (default: 100000)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and rebuild citations table from scratch",
    )

    args = parser.parse_args()

    build_citations_table(
        dsn=resolve_dsn(args.dsn),
        batch_size=args.batch_size,
        commit_interval=args.commit_interval,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    main()
