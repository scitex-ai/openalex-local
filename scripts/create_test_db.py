#!/usr/bin/env python3
"""
Create a small test corpus from OpenAlex API samples.

Downloads sample works from the OpenAlex API and loads them into the corpus
this host resolves to, with the full-text index populated, so the suite runs
against a real PostgreSQL holding the real schema.

ONE SCHEMA, NOT TWO. This script used to declare its own table — different
column names from the real corpus (``authors`` where the corpus has
``authors_json``, ``referenced_works`` where it has ``referenced_works_json``)
— so every test that touched the database was measuring a fixture no build
step produces. It now imports ``scripts/database/_schema.py`` and parses rows
with the same ``parse_work`` the loader uses.

IT DOES NOT DELETE ANYTHING IRREVERSIBLE. The previous version began by
unlinking the database file. Against a shared server that is not available and
would not be acceptable if it were, so this truncates only the tables it
populates, and only when asked to reset.

Usage:
    python scripts/create_test_db.py
    python scripts/create_test_db.py --rows 500
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR / "database"))

from _build_helpers import connect, parse_work, resolve_dsn  # noqa: E402
from _schema import (  # noqa: E402
    FTS_CONFIG,
    FTS_INDEX_DDL,
    WORKS_COLUMNS,
    WORKS_DDL,
    WORKS_INDEXES_DDL,
    search_vector_expression,
)

# The downloaded payload lives under tests/results/ — a gitignored,
# audit-recognized test subdir (PS-302). It is a run artifact, not a committed
# fixture, so it belongs in results/ rather than a bespoke fixtures/ dir (which
# trips PS-302 tests-unknown-subdir).
SAMPLE_JSON_PATH = PROJECT_ROOT / "tests" / "results" / "sample_works.json"

# OpenAlex API
OPENALEX_API = "https://api.openalex.org/works"
USER_AGENT = (
    "openalex-local-tests/0.1 (https://github.com/ywatanabe1989/openalex-local)"
)


def download_sample_works(rows: int = 500, queries: list = None) -> list:
    """
    Download sample works from OpenAlex API.

    Args:
        rows: Number of records per query
        queries: List of search queries for diversity

    Returns:
        List of work metadata dictionaries
    """
    if queries is None:
        # Diverse queries to get varied content
        queries = [
            "neuroscience",
            "machine learning",
            "climate change",
            "cancer",
            "quantum",
        ]

    all_works = []
    rows_per_query = rows // len(queries)

    for query in queries:
        print(f"Downloading '{query}' ({rows_per_query} records)...")

        url = (
            f"{OPENALEX_API}?search={quote(query)}&per_page={min(rows_per_query, 200)}"
        )
        req = Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode())
                works = data.get("results", [])
                all_works.extend(works)
                print(f"  Got {len(works)} records")
        except HTTPError as e:
            print(f"  Error: {e}")

        # Be nice to the API
        time.sleep(1)

    print(f"Total: {len(all_works)} records")
    return all_works


def save_sample_json(works: list, path: Path):
    """Save works to JSON file for reproducibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(works, f)
    print(f"Saved JSON: {path} ({path.stat().st_size / 1024:.1f} KB)")


def load_sample_json(path: Path) -> list:
    """Load works from JSON file."""
    with open(path) as f:
        return json.load(f)


def create_database(works: list, dsn: str, reset: bool = True):
    """
    Load the sample works into the corpus, schema and index included.

    Args:
        works: List of work metadata dictionaries
        dsn: Corpus connection string
        reset: Empty the works table first, so a re-run is reproducible
            rather than cumulative.
    """
    conn = connect(dsn)

    with conn.cursor() as cursor:
        cursor.execute(WORKS_DDL)
        cursor.execute(WORKS_INDEXES_DDL)
        cursor.execute(FTS_INDEX_DDL)
    conn.commit()

    if reset:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE works RESTART IDENTITY")
        conn.commit()

    columns = ", ".join(WORKS_COLUMNS)
    placeholders = ", ".join(["%s"] * len(WORKS_COLUMNS))
    vector = search_vector_expression(title="%s", abstract="%s")
    insert_sql = (
        f"INSERT INTO works ({columns}, search_vector) "
        f"VALUES ({placeholders}, {vector}) "
        "ON CONFLICT (openalex_id) DO NOTHING"
    )

    print(f"Inserting {len(works)} works...")
    rows = []
    for work in works:
        record = parse_work(work)
        if not record["openalex_id"]:
            continue
        rows.append(
            tuple(record[col] for col in WORKS_COLUMNS)
            + (record["title"], record["abstract"])
        )

    with conn.cursor() as cursor:
        cursor.executemany(insert_sql, rows)
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("ANALYZE works")
    conn.commit()
    conn.close()
    print(f"Inserted {len(rows)} works")


def verify_database(dsn: str) -> bool:
    """Verify the test corpus answers the queries the suite will ask."""
    conn = connect(dsn, autocommit=True)

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM works")
        works_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM works WHERE search_vector IS NOT NULL")
        fts_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM works "
            f"WHERE search_vector @@ websearch_to_tsquery('{FTS_CONFIG}', %s)",
            ("neuroscience",),
        )
        search_count = cursor.fetchone()[0]

    conn.close()

    print("\nVerification:")
    print(f"  Works: {works_count}")
    print(f"  Full-text indexed: {fts_count}")
    print(f"  Search 'neuroscience': {search_count} matches")

    if works_count > 0 and fts_count > 0:
        print("\nTest corpus ready!")
        return True
    print("\nError: corpus verification failed")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Create a test corpus from the OpenAlex API"
    )
    parser.add_argument(
        "--rows", type=int, default=500, help="Number of records to download"
    )
    parser.add_argument(
        "--use-cached", action="store_true", help="Use cached JSON if available"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Add to the existing works rather than replacing them",
    )
    args = parser.parse_args()

    dsn = resolve_dsn(args.dsn)

    print("=" * 60)
    print("Creating OpenAlex Test Corpus")
    print("=" * 60)
    print()

    # Download or load sample works
    if args.use_cached and SAMPLE_JSON_PATH.exists():
        print(f"Using cached JSON: {SAMPLE_JSON_PATH}")
        works = load_sample_json(SAMPLE_JSON_PATH)
    else:
        works = download_sample_works(rows=args.rows)
        save_sample_json(works, SAMPLE_JSON_PATH)

    print()

    create_database(works, dsn, reset=not args.keep_existing)

    ok = verify_database(dsn)

    print()
    print("=" * 60)
    print(f"Test corpus: {dsn}")
    print("Run tests with: make test")
    print("=" * 60)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
