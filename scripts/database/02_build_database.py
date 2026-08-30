#!/usr/bin/env python3
# Timestamp: 2026-08-30
"""Build the corpus from an OpenAlex snapshot.

Reads gzipped JSON Lines files from the OpenAlex snapshot and loads the works
data into the PostgreSQL corpus this host resolves to.

Usage:
    python 02_build_database.py [--snapshot-dir PATH] [--dsn DSN] [--batch-size N]

Example:
    python scripts/database/02_build_database.py
    python scripts/database/02_build_database.py --batch-size 50000
"""

import argparse
import gzip
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, parse_work, resolve_dsn  # noqa: E402
from _schema import WORKS_COLUMNS, WORKS_DDL, WORKS_INDEXES_DDL  # noqa: E402

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot" / "works"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


#: This step's own bookkeeping. It is not part of the corpus schema because
#: nothing but this script reads it — a resumable loader's cursor, not data.
PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS _build_progress (
    file_path TEXT PRIMARY KEY,
    records_processed INTEGER,
    completed_at TIMESTAMPTZ DEFAULT NOW()
);
"""

#: The columns this loader writes. Taken from the schema module rather than
#: repeated here, so a column added there is written rather than silently
#: left NULL by a loader nobody remembered to update.
INSERT_COLUMNS = WORKS_COLUMNS


def iter_jsonl_gz(file_path: Path) -> Generator[Dict[str, Any], None, None]:
    """Iterate over gzipped JSON Lines file."""
    with gzip.open(file_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error in {file_path}: {e}")
                    continue


def get_all_gz_files(snapshot_dir: Path) -> List[Path]:
    """Get all .gz files from snapshot directory, sorted."""
    files = []
    for date_dir in sorted(snapshot_dir.iterdir()):
        if date_dir.is_dir() and date_dir.name.startswith("updated_date="):
            for gz_file in sorted(date_dir.glob("*.gz")):
                files.append(gz_file)
    return files


def get_processed_files(conn) -> Set[str]:
    """Get set of already processed file paths."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT file_path FROM _build_progress")
        return {row[0] for row in cursor.fetchall()}


def mark_file_processed(conn, file_path: str, records: int) -> None:
    """Mark a file as processed."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO _build_progress (file_path, records_processed) "
            "VALUES (%s, %s) "
            "ON CONFLICT (file_path) DO UPDATE SET "
            "records_processed = EXCLUDED.records_processed, "
            "completed_at = NOW()",
            (file_path, records),
        )
    conn.commit()


def insert_batch(conn, records: List[Dict[str, Any]]) -> int:
    """Insert a batch of records into the corpus.

    ``ON CONFLICT DO NOTHING`` on ``openalex_id`` keeps the loader restartable:
    a file half-written before a crash is replayed whole, and the rows that
    landed the first time are skipped rather than duplicated.
    """
    if not records:
        return 0

    column_names = ", ".join(INSERT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(INSERT_COLUMNS))
    sql = (
        f"INSERT INTO works ({column_names}) VALUES ({placeholders}) "
        "ON CONFLICT (openalex_id) DO NOTHING"
    )

    values = [tuple(r[col] for col in INSERT_COLUMNS) for r in records]

    with conn.cursor() as cursor:
        cursor.executemany(sql, values)
        inserted = cursor.rowcount
    conn.commit()
    # psycopg reports -1 when a driver cannot attribute a row count to a
    # multi-statement execute. Reporting -1 as "rows inserted" would make the
    # final total meaningless, so fall back to the batch size.
    return inserted if inserted is not None and inserted >= 0 else len(records)


def build_database(
    snapshot_dir: Path,
    dsn: str,
    batch_size: int = 10000,
    store_raw: bool = False,
) -> None:
    """Build the corpus from an OpenAlex snapshot."""
    logger.info(f"Building corpus: {dsn}")
    logger.info(f"Snapshot directory: {snapshot_dir}")
    logger.info(f"Batch size: {batch_size}")

    conn = connect(dsn)

    # Create schema. Indices come with it here rather than after the load: the
    # loader is restartable and may be run against a corpus that already has
    # rows, so "create the indices at the end" has no single end to be at.
    with conn.cursor() as cursor:
        cursor.execute(WORKS_DDL)
        cursor.execute(WORKS_INDEXES_DDL)
        cursor.execute(PROGRESS_DDL)
    conn.commit()

    # Get files to process
    all_files = get_all_gz_files(snapshot_dir)
    processed_files = get_processed_files(conn)

    files_to_process = [f for f in all_files if str(f) not in processed_files]

    logger.info(f"Total files: {len(all_files)}")
    logger.info(f"Already processed: {len(processed_files)}")
    logger.info(f"Files to process: {len(files_to_process)}")

    if not files_to_process:
        logger.info("All files already processed!")
        conn.close()
        return

    # Process files
    total_records = 0
    start_time = time.time()

    for file_idx, gz_file in enumerate(files_to_process):
        file_start = time.time()
        batch = []
        file_records = 0

        logger.info(f"[{file_idx + 1}/{len(files_to_process)}] Processing: {gz_file.name}")

        for data in iter_jsonl_gz(gz_file):
            try:
                record = parse_work(data, store_raw=store_raw)
                batch.append(record)
                file_records += 1

                if len(batch) >= batch_size:
                    inserted = insert_batch(conn, batch)
                    total_records += inserted
                    batch = []

                    # Progress update
                    if file_records % 100000 == 0:
                        elapsed = time.time() - start_time
                        rate = total_records / elapsed if elapsed > 0 else 0
                        logger.info(
                            f"  Progress: {file_records:,} records | "
                            f"Total: {total_records:,} | "
                            f"Rate: {rate:.0f}/s"
                        )

            except Exception as e:
                logger.warning(f"Error processing record: {e}")
                conn.rollback()
                batch = []
                continue

        # Insert remaining batch
        if batch:
            inserted = insert_batch(conn, batch)
            total_records += inserted

        # Mark file as processed
        mark_file_processed(conn, str(gz_file), file_records)

        file_elapsed = time.time() - file_start
        logger.info(
            f"  Completed: {file_records:,} records in {file_elapsed:.1f}s "
            f"({file_records / file_elapsed:.0f}/s)"
        )

    # Final stats
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Build completed!")
    logger.info(f"Total records: {total_records:,}")
    logger.info(f"Total time: {elapsed / 3600:.1f} hours")
    logger.info(f"Average rate: {total_records / elapsed:.0f} records/s")

    # Record the build counters. They live in the fleet store, not in a table
    # inside the corpus, so a status call can read them without opening a
    # 200 GB database.
    from openalex_local._core.state import set_metadata

    set_metadata("build_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("total_works", str(total_records))

    # Refresh the planner's statistics for the rows just loaded.
    logger.info("Running ANALYZE for query optimization...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE works")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_size_pretty(pg_total_relation_size('works'))")
        size = cursor.fetchone()[0]
    conn.close()
    logger.info(f"Corpus written: {dsn}")
    logger.info(f"works table size: {size}")


def main():
    parser = argparse.ArgumentParser(
        description="Build the OpenAlex corpus from a snapshot"
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help=f"Path to snapshot works directory (default: {DEFAULT_SNAPSHOT_DIR})",
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
        help="Batch size for corpus inserts (default: 10000)",
    )
    parser.add_argument(
        "--store-raw",
        action="store_true",
        help="Store raw JSON in the corpus (increases size significantly)",
    )

    args = parser.parse_args()

    if not args.snapshot_dir.exists():
        logger.error(f"Snapshot directory not found: {args.snapshot_dir}")
        sys.exit(1)

    build_database(
        snapshot_dir=args.snapshot_dir,
        dsn=resolve_dsn(args.dsn),
        batch_size=args.batch_size,
        store_raw=args.store_raw,
    )


if __name__ == "__main__":
    main()
