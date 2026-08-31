#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Differential update for the OpenAlex corpus.

Downloads only snapshot directories newer than the last sync date, then merges
new/updated records into the existing corpus.

Usage:
    python 10_differential_update.py [--dsn DSN] [--snapshot-dir PATH]
    python 10_differential_update.py --since 2026-03-01
    python 10_differential_update.py --dry-run

Steps:
    1. Read the last sync date from the build-metadata store
    2. List S3 directories with updated_date > last sync
    3. Download only those directories (aws s3 sync with --include filter)
    4. Parse and upsert records (INSERT ... ON CONFLICT DO UPDATE)
    5. Record the new last_sync_date
"""

import argparse
import gzip
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from _build_helpers import connect, parse_work, resolve_dsn  # noqa: E402
from _schema import (  # noqa: E402
    FTS_INDEX_DDL,
    WORKS_COLUMNS,
    WORKS_DDL,
    WORKS_INDEXES_DDL,
    search_vector_expression,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot" / "works"
# OpenAlex restructured the snapshot in 2026: works moved from
# s3://openalex/data/works/ to s3://openalex/data/jsonl/works/ (updated_date=
# partitions unchanged). Overridable via OPENALEX_S3_BASE for future moves.
OPENALEX_S3_BASE = os.environ.get(
    "OPENALEX_S3_BASE", "s3://openalex/data/jsonl/works/"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_last_sync_date() -> Optional[str]:
    """Get last sync date from the build-metadata store.

    Returns None when there is no history OR the store cannot be reached. The
    caller treats both as "no history" and falls back to a 30-day window, which
    re-downloads rather than skipping: the failure mode of guessing too early is
    wasted bandwidth, and of guessing too late is missing records silently.
    """
    try:
        from openalex_local._core.state import get_metadata

        return get_metadata("last_sync_date")
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        logger.warning(f"Could not read last_sync_date: {exc}")
        return None


def set_last_sync_date(date_str: str) -> None:
    """Record the last sync date in the build-metadata store."""
    from openalex_local._core.state import set_metadata

    set_metadata("last_sync_date", date_str)


def list_s3_updated_dates(since: Optional[str] = None) -> List[str]:
    """List updated_date directories from S3.

    Parameters
    ----------
    since : str, optional
        Only return dates after this (YYYY-MM-DD format).

    Returns
    -------
    list[str]
        Sorted list of date strings (YYYY-MM-DD).
    """
    logger.info("Listing S3 directories...")
    cmd = [
        "aws", "s3", "ls", OPENALEX_S3_BASE,
        "--no-sign-request",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to list S3: {e}")
        return []

    dates = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "updated_date=" in line:
            # Format: "PRE updated_date=2026-03-15/"
            part = line.split("updated_date=")[-1].rstrip("/")
            if part:
                dates.append(part)

    dates.sort()

    if since:
        dates = [d for d in dates if d > since]

    logger.info(f"Found {len(dates)} directories" + (f" since {since}" if since else ""))
    return dates


def download_date_directories(
    dates: List[str],
    snapshot_dir: Path,
) -> List[Path]:
    """Download specific updated_date directories from S3.

    Returns list of downloaded directory paths.
    """
    downloaded = []
    for i, date in enumerate(dates):
        s3_path = f"{OPENALEX_S3_BASE}updated_date={date}/"
        local_path = snapshot_dir / f"updated_date={date}"
        local_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"[{i+1}/{len(dates)}] Downloading updated_date={date}...")

        cmd = [
            "aws", "s3", "sync",
            s3_path, str(local_path),
            "--no-sign-request",
        ]
        try:
            subprocess.run(cmd, check=True)
            downloaded.append(local_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to download {date}: {e}")

    return downloaded


def upsert_batch(conn, records: list) -> int:
    """Upsert a batch of records."""
    if not records:
        return 0

    # The search vector is computed in the SAME statement that writes the row.
    # It cannot reference the row being inserted, so title and abstract are
    # bound twice -- once for their columns, once for the vector expression.
    # Recomputing here rather than in a later pass is what stops an updated
    # title from keeping its old index entry: a stale hit is indistinguishable
    # from a correct one at the call site.
    columns = ", ".join(WORKS_COLUMNS)
    placeholders = ", ".join(["%s"] * len(WORKS_COLUMNS))
    updates = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in WORKS_COLUMNS if col != "openalex_id"
    )
    vector = search_vector_expression(title="%s", abstract="%s")
    sql = (
        f"INSERT INTO works ({columns}, search_vector) "
        f"VALUES ({placeholders}, {vector}) "
        f"ON CONFLICT (openalex_id) DO UPDATE SET {updates}, "
        "search_vector = EXCLUDED.search_vector"
    )

    values = [
        tuple(r[col] for col in WORKS_COLUMNS) + (r["title"], r["abstract"])
        for r in records
    ]

    with conn.cursor() as cursor:
        cursor.executemany(sql, values)
        upserted = cursor.rowcount
    conn.commit()
    return upserted if upserted is not None and upserted >= 0 else len(records)


def process_date_directory(
    date_dir: Path,
    conn,
    batch_size: int = 10000,
    store_raw: bool = False,
) -> int:
    """Process all .gz files in a date directory and upsert into the corpus."""
    gz_files = sorted(date_dir.glob("*.gz"))
    if not gz_files:
        return 0

    total = 0
    for gz_file in gz_files:
        batch = []

        with gzip.open(gz_file, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    record = parse_work(data, store_raw=store_raw)
                    batch.append(record)

                    if len(batch) >= batch_size:
                        total += upsert_batch(conn, batch)
                        batch = []
                except Exception as e:  # noqa: BLE001 - one bad line, not one bad run
                    logger.warning(f"Error processing record in {gz_file.name}: {e}")
                    conn.rollback()
                    batch = []
                    continue

        if batch:
            total += upsert_batch(conn, batch)

    return total


def differential_update(
    dsn: str,
    snapshot_dir: Path,
    since: Optional[str] = None,
    batch_size: int = 10000,
    store_raw: bool = False,
    dry_run: bool = False,
    skip_download: bool = False,
    rebuild_fts: bool = True,
) -> dict:
    """Run differential update.

    Parameters
    ----------
    dsn : str
        Corpus connection string.
    snapshot_dir : Path
        Path to snapshot works directory.
    since : str, optional
        Override: only update from this date (YYYY-MM-DD).
    batch_size : int
        Records per corpus batch.
    store_raw : bool
        Store raw JSON in the corpus.
    dry_run : bool
        List what would be downloaded without doing it.
    skip_download : bool
        Skip download, process existing files only.
    rebuild_fts : bool
        Ensure the full-text index exists after the update. The vectors
        themselves are written by the upsert, so this is a cheap guard rather
        than a rebuild.

    Returns
    -------
    dict
        Statistics: dates_processed, records_upserted, elapsed_seconds.
    """
    if since is None:
        since = get_last_sync_date()
        if since:
            logger.info(f"Last sync date: {since}")

    if since is None:
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        logger.info(f"No sync history — defaulting to last 30 days ({since})")

    # List available updates
    new_dates = list_s3_updated_dates(since=since)

    if not new_dates:
        logger.info("No new updates available.")
        return {
            "dates_processed": 0,
            "records_upserted": 0,
            "elapsed_seconds": 0,
            "last_sync_date": since,
        }

    logger.info(f"Updates available: {len(new_dates)} date directories")
    logger.info(f"  From: {new_dates[0]}")
    logger.info(f"  To:   {new_dates[-1]}")

    if dry_run:
        logger.info("DRY RUN — no changes will be made.")
        for d in new_dates:
            logger.info(f"  Would download: updated_date={d}")
        return {
            "dates_processed": 0,
            "records_upserted": 0,
            "elapsed_seconds": 0,
            "dry_run": True,
        }

    conn = connect(dsn)

    # The corpus may not exist yet on a first run.
    with conn.cursor() as cursor:
        cursor.execute(WORKS_DDL)
        cursor.execute(WORKS_INDEXES_DDL)
    conn.commit()

    start_time = time.time()

    # Download new directories
    if not skip_download:
        downloaded = download_date_directories(new_dates, snapshot_dir)
        logger.info(f"Downloaded {len(downloaded)} directories.")
    else:
        downloaded = [
            snapshot_dir / f"updated_date={d}"
            for d in new_dates
            if (snapshot_dir / f"updated_date={d}").exists()
        ]
        logger.info(f"Skipping download — found {len(downloaded)} existing directories.")

    # Process and upsert
    total_upserted = 0
    for i, date_dir in enumerate(downloaded):
        date = date_dir.name.replace("updated_date=", "")
        logger.info(f"[{i+1}/{len(downloaded)}] Processing {date}...")

        upserted = process_date_directory(
            date_dir, conn,
            batch_size=batch_size,
            store_raw=store_raw,
        )
        total_upserted += upserted
        logger.info(f"  Upserted {upserted:,} records.")

    # Update last sync date
    if new_dates:
        set_last_sync_date(new_dates[-1])
        logger.info(f"Updated last_sync_date to {new_dates[-1]}")

    if rebuild_fts and total_upserted > 0:
        logger.info("Ensuring the full-text index exists...")
        with conn.cursor() as cursor:
            cursor.execute(FTS_INDEX_DDL)
        conn.commit()

    from openalex_local._core.state import set_metadata

    set_metadata("last_update_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("last_update_records", str(total_upserted))

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Differential update complete!")
    logger.info(f"  Dates processed: {len(downloaded)}")
    logger.info(f"  Records upserted: {total_upserted:,}")
    logger.info(f"  Elapsed: {elapsed / 60:.1f} minutes")

    conn.close()
    return {
        "dates_processed": len(downloaded),
        "records_upserted": total_upserted,
        "elapsed_seconds": elapsed,
        "last_sync_date": new_dates[-1] if new_dates else since,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Differential update for the OpenAlex corpus"
    )
    parser.add_argument(
        "--dsn", default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR,
        help=f"Snapshot directory (default: {DEFAULT_SNAPSHOT_DIR})",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="Override start date (YYYY-MM-DD). Default: the recorded sync date.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=10000,
        help="Batch size for inserts (default: 10000)",
    )
    parser.add_argument(
        "--store-raw", action="store_true",
        help="Store raw JSON in the corpus",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List updates without downloading or processing",
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Skip download, process existing snapshot files only",
    )
    parser.add_argument(
        "--no-fts-rebuild", action="store_true",
        help="Skip the full-text index check after the update",
    )

    args = parser.parse_args()

    stats = differential_update(
        dsn=resolve_dsn(args.dsn),
        snapshot_dir=args.snapshot_dir,
        since=args.since,
        batch_size=args.batch_size,
        store_raw=args.store_raw,
        dry_run=args.dry_run,
        skip_download=args.skip_download,
        rebuild_fts=not args.no_fts_rebuild,
    )

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()

# EOF
