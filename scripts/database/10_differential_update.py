#!/usr/bin/env python3
"""Run the packaged OpenAlex incremental updater from a checkout."""

import argparse
import json
from pathlib import Path

from openalex_local._core._build_helpers import resolve_dsn
from openalex_local._core._differential_update import differential_update

DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshot" / "works"


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
