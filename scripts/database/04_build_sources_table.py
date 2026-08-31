#!/usr/bin/env python3
# Timestamp: 2026-08-30
"""Build the sources table from an OpenAlex snapshot (journal metrics).

Reads the sources entity from the OpenAlex snapshot and builds a sources table
with journal-level metrics including impact factor (2yr_mean_citedness),
h-index, citation counts, and other bibliometrics.

Usage:
    python 04_build_sources_table.py [--snapshot-dir PATH] [--dsn DSN]

Example:
    python scripts/database/04_build_sources_table.py
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

from _build_helpers import connect, resolve_dsn  # noqa: E402
from _schema import SOURCES_DDL  # noqa: E402

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot" / "sources"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


#: This step's resumable-loader cursor. Not corpus data, so it stays local to
#: the script that owns it.
PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS _sources_build_progress (
    file_path TEXT PRIMARY KEY,
    records_processed INTEGER,
    completed_at TIMESTAMPTZ DEFAULT NOW()
);
"""

#: Column order for the upsert. One tuple, so the statement and the values
#: cannot disagree.
COLUMNS = (
    "openalex_id",
    "issn_l",
    "issns",
    "display_name",
    "display_name_lower",
    "type",
    "host_organization",
    "country_code",
    "homepage_url",
    "works_count",
    "oa_works_count",
    "cited_by_count",
    "two_year_mean_citedness",
    "h_index",
    "i10_index",
    "is_oa",
    "is_in_doaj",
    "is_core",
    "first_publication_year",
    "last_publication_year",
    "apc_usd",
)


def parse_source(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse OpenAlex source JSON into a sources record."""
    openalex_id = data.get("id", "").replace("https://openalex.org/", "")

    issns = data.get("issn") or []
    issn_l = data.get("issn_l")

    summary_stats = data.get("summary_stats") or {}

    display_name = data.get("display_name")

    return {
        "openalex_id": openalex_id,
        "issn_l": issn_l,
        "issns": json.dumps(issns) if issns else None,
        "display_name": display_name,
        "display_name_lower": display_name.lower() if display_name else None,
        "type": data.get("type"),
        "host_organization": data.get("host_organization_name"),
        "country_code": data.get("country_code"),
        "homepage_url": data.get("homepage_url"),

        # Bibliometrics
        "works_count": data.get("works_count", 0),
        "oa_works_count": data.get("oa_works_count", 0),
        "cited_by_count": data.get("cited_by_count", 0),

        # Impact metrics
        "two_year_mean_citedness": summary_stats.get("2yr_mean_citedness"),
        "h_index": summary_stats.get("h_index"),
        "i10_index": summary_stats.get("i10_index"),

        # OA status — real booleans, matching the column types.
        "is_oa": bool(data.get("is_oa")),
        "is_in_doaj": bool(data.get("is_in_doaj")),
        "is_core": bool(data.get("is_core")),

        # Temporal
        "first_publication_year": data.get("first_publication_year"),
        "last_publication_year": data.get("last_publication_year"),

        # APC
        "apc_usd": data.get("apc_usd"),
    }


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
    """Get all .gz files from snapshot directory, sorted by date (newest first for dedup)."""
    files = []
    for date_dir in sorted(snapshot_dir.iterdir(), reverse=True):  # Newest first
        if date_dir.is_dir() and date_dir.name.startswith("updated_date="):
            for gz_file in sorted(date_dir.glob("*.gz")):
                files.append(gz_file)
    return files


def get_processed_files(conn) -> Set[str]:
    """Get set of already processed file paths."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('_sources_build_progress') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return set()
        cursor.execute("SELECT file_path FROM _sources_build_progress")
        return {row[0] for row in cursor.fetchall()}


def mark_file_processed(conn, file_path: str, records: int) -> None:
    """Mark a file as processed."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO _sources_build_progress (file_path, records_processed) "
            "VALUES (%s, %s) "
            "ON CONFLICT (file_path) DO UPDATE SET "
            "records_processed = EXCLUDED.records_processed, "
            "completed_at = NOW()",
            (file_path, records),
        )
    conn.commit()


def build_issn_lookup(conn) -> int:
    """Build ISSN lookup table from sources.

    Every ISSN a source declares maps to that source. The whole table is
    rebuilt in one statement rather than row by row: the previous loop issued
    one INSERT per ISSN and counted its ATTEMPTS, so the number it reported
    was larger than the number of rows the table actually held whenever a
    duplicate was skipped.
    """
    logger.info("Building ISSN lookup table...")

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM issn_lookup")
        cursor.execute(
            """
            INSERT INTO issn_lookup (issn, source_id)
            SELECT DISTINCT ON (issn) issn, id
            FROM (
                SELECT id, issn_l AS issn FROM sources WHERE issn_l IS NOT NULL
                UNION ALL
                SELECT s.id, j.value AS issn
                FROM sources s,
                     LATERAL json_array_elements_text(s.issns::json) AS j(value)
                WHERE s.issns IS NOT NULL
            ) AS every_issn
            WHERE issn IS NOT NULL AND issn <> ''
            ORDER BY issn, id
            ON CONFLICT (issn) DO NOTHING
            """
        )
        cursor.execute("SELECT COUNT(*) FROM issn_lookup")
        lookup_count = cursor.fetchone()[0]
    conn.commit()

    logger.info(f"ISSN lookup table built with {lookup_count} entries")
    return lookup_count


def build_sources_table(
    snapshot_dir: Path,
    dsn: str,
    batch_size: int = 5000,
    rebuild: bool = False,
) -> None:
    """Build sources table from OpenAlex snapshot."""
    logger.info(f"Building sources table in: {dsn}")
    logger.info(f"Sources snapshot directory: {snapshot_dir}")

    if not snapshot_dir.exists():
        logger.error(f"Sources snapshot directory not found: {snapshot_dir}")
        logger.error("Run: python scripts/database/01_download_snapshot.py --entity sources")
        sys.exit(1)

    conn = connect(dsn)

    if rebuild:
        logger.info("Rebuilding: dropping existing sources tables...")
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS issn_lookup")
            cursor.execute("DROP TABLE IF EXISTS sources")
            cursor.execute("DROP TABLE IF EXISTS _sources_build_progress")
        conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(SOURCES_DDL)
        cursor.execute(PROGRESS_DDL)
    conn.commit()

    # Get files to process
    all_files = get_all_gz_files(snapshot_dir)
    processed_files = get_processed_files(conn)

    files_to_process = [f for f in all_files if str(f) not in processed_files]

    logger.info(f"Total source files: {len(all_files)}")
    logger.info(f"Already processed: {len(processed_files)}")
    logger.info(f"Files to process: {len(files_to_process)}")

    if not files_to_process:
        logger.info("All source files already processed!")
        # Still rebuild ISSN lookup in case it's needed
        build_issn_lookup(conn)
        conn.close()
        return

    # Process files
    total_records = 0
    start_time = time.time()

    column_names = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    updates = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in COLUMNS if col != "openalex_id"
    )
    insert_sql = (
        f"INSERT INTO sources ({column_names}) VALUES ({placeholders}) "
        f"ON CONFLICT (openalex_id) DO UPDATE SET {updates}"
    )

    for file_idx, gz_file in enumerate(files_to_process):
        file_start = time.time()
        batch = []
        file_records = 0

        logger.info(f"[{file_idx + 1}/{len(files_to_process)}] Processing: {gz_file}")

        for data in iter_jsonl_gz(gz_file):
            try:
                record = parse_source(data)
                batch.append(tuple(record[col] for col in COLUMNS))
                file_records += 1
                total_records += 1

                if len(batch) >= batch_size:
                    with conn.cursor() as cursor:
                        cursor.executemany(insert_sql, batch)
                    conn.commit()
                    batch = []

            except Exception as e:
                logger.warning(f"Error processing source record: {e}")
                conn.rollback()
                batch = []
                continue

        # Insert remaining batch
        if batch:
            with conn.cursor() as cursor:
                cursor.executemany(insert_sql, batch)
            conn.commit()

        # Mark file as processed
        mark_file_processed(conn, str(gz_file), file_records)

        file_elapsed = time.time() - file_start
        logger.info(f"  Completed: {file_records:,} records in {file_elapsed:.1f}s")

    # Build ISSN lookup table
    build_issn_lookup(conn)

    # Final stats
    elapsed = time.time() - start_time

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM sources")
        total_sources = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM issn_lookup")
        total_issns = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM sources WHERE two_year_mean_citedness IS NOT NULL"
        )
        sources_with_if = cursor.fetchone()[0]

    logger.info("=" * 60)
    logger.info("Sources table build completed!")
    logger.info(f"Total sources: {total_sources:,}")
    logger.info(f"Sources with impact factor: {sources_with_if:,}")
    logger.info(f"Total ISSN lookups: {total_issns:,}")
    logger.info(f"Total time: {elapsed:.1f}s")

    from openalex_local._core.state import set_metadata

    set_metadata("sources_build_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("total_sources", str(total_sources))

    # Analyze for query optimization
    logger.info("Running ANALYZE for query optimization...")
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE sources")
        cursor.execute("ANALYZE issn_lookup")
    conn.commit()

    conn.close()
    logger.info("Sources table ready!")


def main():
    parser = argparse.ArgumentParser(
        description="Build sources table from OpenAlex snapshot"
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help=f"Path to sources snapshot directory (default: {DEFAULT_SNAPSHOT_DIR})",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Batch size for inserts (default: 5000)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and rebuild sources tables from scratch",
    )

    args = parser.parse_args()

    build_sources_table(
        snapshot_dir=args.snapshot_dir,
        dsn=resolve_dsn(args.dsn),
        batch_size=args.batch_size,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    main()
