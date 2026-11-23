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

import gzip
import json
import os
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import List, Optional

import scitex_logging

from ._build_helpers import connect, parse_work
from ._schema import (
    FTS_INDEX_DDL,
    WORKS_COLUMNS,
    WORKS_DDL,
    WORKS_INDEXES_DDL,
    search_vector_expression,
)

# OpenAlex restructured the snapshot in 2026: works moved from
# s3://openalex/data/works/ to s3://openalex/data/jsonl/works/ (updated_date=
# partitions unchanged). Overridable via OPENALEX_S3_BASE for future moves.
OPENALEX_S3_BASE = os.environ.get(
    "OPENALEX_S3_BASE", "s3://openalex/data/jsonl/works/"
)

logger = scitex_logging.getLogger(__name__)


def get_last_sync_date() -> Optional[str]:
    """Read the date of the last completed update."""
    from openalex_local._core.state import get_metadata

    return get_metadata("last_sync_date")


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
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

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
        subprocess.run(cmd, check=True)
        downloaded.append(local_path)

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
        raise FileNotFoundError(f"No snapshot files in {date_dir}")

    total = 0
    for gz_file in gz_files:
        batch = []

        with gzip.open(gz_file, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = parse_work(json.loads(line), store_raw=store_raw)
                batch.append(record)
                if len(batch) >= batch_size:
                    total += upsert_batch(conn, batch)
                    batch = []

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
        raise ValueError(
            "No sync checkpoint recorded. Pass --since with the date of the corpus snapshot."
        )

    # List available updates
    new_dates = list_s3_updated_dates(since=since)

    if not new_dates:
        logger.info("No new updates available.")
        return {
            "dates_processed": 0,
            "records_upserted": 0,
            "elapsed_seconds": 0,
            "last_sync_date": since,
            "dry_run": dry_run,
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

    start_time = time.time()
    if skip_download:
        downloaded = [snapshot_dir / f"updated_date={date}" for date in new_dates]
    else:
        downloaded = download_date_directories(new_dates, snapshot_dir)

    expected = {f"updated_date={date}" for date in new_dates}
    available = {path.name for path in downloaded if any(path.glob("*.gz"))}
    if expected != available:
        missing = ", ".join(sorted(expected - available))
        raise RuntimeError(f"OpenAlex snapshot partitions missing or empty: {missing}")

    with closing(connect(dsn)) as conn:
        with conn.cursor() as cursor:
            cursor.execute(WORKS_DDL)
            cursor.execute(WORKS_INDEXES_DDL)
        conn.commit()

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

        if rebuild_fts and total_upserted > 0:
            logger.info("Ensuring the full-text index exists...")
            with conn.cursor() as cursor:
                cursor.execute(FTS_INDEX_DDL)
            conn.commit()

    from openalex_local._core.state import set_metadata

    set_metadata("last_update_completed", time.strftime("%Y-%m-%d %H:%M:%S"))
    set_metadata("last_update_records", str(total_upserted))
    set_last_sync_date(new_dates[-1])
    logger.info(f"Updated last_sync_date to {new_dates[-1]}")

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Differential update complete!")
    logger.info(f"  Dates processed: {len(downloaded)}")
    logger.info(f"  Records upserted: {total_upserted:,}")
    logger.info(f"  Elapsed: {elapsed / 60:.1f} minutes")

    return {
        "dates_processed": len(downloaded),
        "records_upserted": total_upserted,
        "elapsed_seconds": elapsed,
        "last_sync_date": new_dates[-1] if new_dates else since,
    }


# EOF
