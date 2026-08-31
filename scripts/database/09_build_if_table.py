#!/usr/bin/env python3
# Timestamp: 2026-02-05
"""Build precomputed Impact Factor table using JCR definition.

JCR Impact Factor Formula:
    IF(Year Y) = Citations in Y to articles from (Y-1, Y-2) / Articles in (Y-1, Y-2)

This script can run in two modes:
1. Validation mode (--validate): Calculate IF for 30 sample journals and compare with JCR
2. Full mode (--full): Precompute IF for all journals (takes hours)

Usage:
    python 07_build_if_table.py --validate          # Quick validation with 30 journals
    python 07_build_if_table.py --full              # Full precomputation
    python 07_build_if_table.py --issn 0028-0836    # Single journal (Nature)

Example:
    python scripts/database/07_build_if_table.py --validate
    python scripts/database/07_build_if_table.py --full --year 2023
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _build_helpers import connect, resolve_dsn  # noqa: E402
from _schema import IF_DDL  # noqa: E402

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JCR_REFERENCE_PATH = Path("/home/ywatanabe/proj/crossref-local/examples/03_impact_factor/01_compare_jcr_out/all_combined.csv")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)



def load_jcr_reference() -> Dict[str, dict]:
    """Load JCR reference data for validation."""
    if not JCR_REFERENCE_PATH.exists():
        logger.warning(f"JCR reference file not found: {JCR_REFERENCE_PATH}")
        return {}

    jcr_data = {}
    with open(JCR_REFERENCE_PATH, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn = row.get('issn', '').strip()
            if issn:
                jcr_data[issn] = {
                    'journal': row.get('journal', ''),
                    'jcr_if': float(row['jcr_if']) if row.get('jcr_if') else None,
                }
    return jcr_data


def calculate_if_for_journal(
    conn,
    issn: str,
    year: int,
    window: int = 2,
    citable_only: bool = True,
    min_references: int = 20,
) -> Tuple[Optional[float], int, int]:
    """Calculate JCR-style Impact Factor for a single journal-year.

    JCR methodology:
    - Only counts "citable items" (research articles with >20 references)
    - Excludes news, editorials, letters, corrections

    Args:
        conn: Database connection
        issn: Journal ISSN
        year: Target year (citations FROM this year)
        window: Citation window (2 or 5 years)
        citable_only: If True, only count citable items (JCR methodology)
        min_references: Minimum references to be considered citable (default: 20)

    Returns:
        Tuple of (impact_factor, citations_count, articles_count)
    """
    # Years in the window (e.g., for 2023 with window=2: 2021, 2022)
    window_years = list(range(year - window, year))

    # JCR citable items filter: articles with >20 references. The count is
    # read from the precomputed ref_count column (script 07) rather than
    # measured from the JSON on every row, which is what made this query
    # scan instead of using idx_works_issn_year_refcount.
    if citable_only:
        citable_filter = "AND w.ref_count > %(min_refs)s"
    else:
        citable_filter = ""

    params = {
        "issn": issn,
        "years": window_years,
        "year": year,
        "min_refs": min_references,
    }

    # Denominator: Count citable articles published in window years
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM works w
            WHERE w.issn = %(issn)s AND w.year = ANY(%(years)s)
              AND w.referenced_works_json IS NOT NULL
            {citable_filter}
            """,
            params,
        )
        articles_count = cursor.fetchone()[0]

    if articles_count == 0:
        return None, 0, 0

    # Numerator: Count citations in target year to citable articles in window
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM citations c
            JOIN works w ON c.cited_id = w.openalex_id
            WHERE w.issn = %(issn)s
              AND w.year = ANY(%(years)s)
              AND c.citing_year = %(year)s
              AND w.referenced_works_json IS NOT NULL
              {citable_filter}
            """,
            params,
        )
        citations_count = cursor.fetchone()[0]

    # Calculate IF
    impact_factor = round(citations_count / articles_count, 1)

    return impact_factor, citations_count, articles_count


def get_journal_name(conn, issn: str) -> Optional[str]:
    """Get journal name from sources table."""
    # Try issn_lookup first
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.display_name
            FROM issn_lookup l
            JOIN sources s ON l.source_id = s.id
            WHERE l.issn = %s
            LIMIT 1
            """,
            (issn,),
        )
        row = cursor.fetchone()
    if row:
        return row[0]

    # Fallback to sources.issn_l
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT display_name FROM sources WHERE issn_l = %s LIMIT 1",
            (issn,),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def validate_with_jcr(dsn: str, year: int = 2023, citable_only: bool = True) -> None:
    """Validate IF calculation against JCR reference data."""
    logger.info("=" * 60)
    logger.info("VALIDATION MODE: Comparing with JCR reference data")
    logger.info(f"Citable items only: {citable_only} (JCR methodology: >20 references)")
    logger.info("=" * 60)

    # Load JCR reference
    jcr_data = load_jcr_reference()
    if not jcr_data:
        logger.error("No JCR reference data available")
        return

    logger.info(f"Loaded {len(jcr_data)} journals from JCR reference")

    conn = connect(dsn, autocommit=True)

    # Check if citations table exists
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('citations') IS NOT NULL")
        has_citations = bool(cursor.fetchone()[0])
    if not has_citations:
        logger.error("Citations table not found. Run 05_build_citations_table.py first.")
        conn.close()
        return

    results = []
    logger.info(f"\nCalculating IF for year {year} (window: 2 years)")
    logger.info("-" * 80)
    logger.info(f"{'Journal':<40} {'ISSN':<12} {'Calc IF':>8} {'JCR IF':>8} {'Ratio':>8}")
    logger.info("-" * 80)

    for issn, jcr_info in list(jcr_data.items())[:30]:  # First 30 journals
        jcr_if = jcr_info['jcr_if']
        journal = jcr_info['journal'][:38]

        calc_if, citations, articles = calculate_if_for_journal(conn, issn, year, citable_only=citable_only)

        if calc_if is not None and jcr_if is not None and jcr_if > 0:
            ratio = calc_if / jcr_if
            ratio_str = f"{ratio:.2f}"
        else:
            ratio = None
            ratio_str = "N/A"

        calc_if_str = f"{calc_if:.1f}" if calc_if is not None else "N/A"
        jcr_if_str = f"{jcr_if:.1f}" if jcr_if is not None else "N/A"

        logger.info(f"{journal:<40} {issn:<12} {calc_if_str:>8} {jcr_if_str:>8} {ratio_str:>8}")

        results.append({
            'journal': jcr_info['journal'],
            'issn': issn,
            'calc_if': calc_if,
            'jcr_if': jcr_if,
            'ratio': ratio,
            'citations': citations,
            'articles': articles,
        })

    conn.close()

    # Summary statistics
    valid_ratios = [r['ratio'] for r in results if r['ratio'] is not None]
    if valid_ratios:
        avg_ratio = sum(valid_ratios) / len(valid_ratios)
        logger.info("-" * 80)
        logger.info(f"Average ratio (Calculated/JCR): {avg_ratio:.2f}")
        logger.info(f"Journals with data: {len(valid_ratios)}/{len(results)}")

        # Count matches (ratio between 0.8 and 1.2)
        good_matches = sum(1 for r in valid_ratios if 0.8 <= r <= 1.2)
        logger.info(f"Good matches (0.8-1.2 ratio): {good_matches}/{len(valid_ratios)}")

    # Save results
    output_path = PROJECT_ROOT / "data" / "if_validation_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nResults saved to: {output_path}")


def build_full_if_table(
    dsn: str,
    year: int = 2023,
    window: int = 2,
    limit: Optional[int] = None,
) -> None:
    """Build full precomputed IF table for all journals."""
    logger.info("=" * 60)
    logger.info("FULL MODE: Precomputing IF for all journals")
    logger.info("=" * 60)

    conn = connect(dsn)

    # Create table
    with conn.cursor() as cursor:
        cursor.execute(IF_DDL)
    conn.commit()

    # Get all unique ISSNs from works table
    logger.info("Fetching unique ISSNs...")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT issn FROM works WHERE issn IS NOT NULL AND issn != ''"
        )
        issns = [row[0] for row in cursor.fetchall()]

    if limit:
        issns = issns[:limit]

    logger.info(f"Processing {len(issns):,} journals for year {year}")

    start_time = time.time()
    processed = 0
    inserted = 0

    for issn in issns:
        calc_if, citations, articles = calculate_if_for_journal(conn, issn, year, window)

        if calc_if is not None:
            journal_name = get_journal_name(conn, issn)

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO journal_impact_factors
                    (issn, journal_name, year, window, impact_factor,
                     citations_count, articles_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (issn, year, window) DO UPDATE SET
                        journal_name = EXCLUDED.journal_name,
                        impact_factor = EXCLUDED.impact_factor,
                        citations_count = EXCLUDED.citations_count,
                        articles_count = EXCLUDED.articles_count,
                        calculated_at = NOW()
                    """,
                    (issn, journal_name, year, window, calc_if, citations, articles),
                )
            inserted += 1

        processed += 1

        if processed % 1000 == 0:
            conn.commit()
            elapsed = time.time() - start_time
            rate = processed / elapsed
            eta = (len(issns) - processed) / rate / 60
            logger.info(f"Progress: {processed:,}/{len(issns):,} | Inserted: {inserted:,} | Rate: {rate:.0f}/s | ETA: {eta:.1f}m")

    conn.commit()

    # Final stats
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"Completed in {elapsed/60:.1f} minutes")
    logger.info(f"Journals processed: {processed:,}")
    logger.info(f"IFs calculated: {inserted:,}")

    conn.close()


def calculate_single_journal(dsn: str, issn: str, year: int = 2023) -> None:
    """Calculate IF for a single journal (for debugging)."""
    conn = connect(dsn, autocommit=True)

    journal_name = get_journal_name(conn, issn)
    calc_if, citations, articles = calculate_if_for_journal(conn, issn, year)

    logger.info(f"Journal: {journal_name or 'Unknown'}")
    logger.info(f"ISSN: {issn}")
    logger.info(f"Year: {year}")
    logger.info(f"Articles in window ({year-2}-{year-1}): {articles}")
    logger.info(f"Citations in {year}: {citations}")
    logger.info(f"Impact Factor: {calc_if:.1f}" if calc_if else "Impact Factor: N/A")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Build precomputed Impact Factor table (JCR definition)"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Corpus DSN (default: the store this host resolves to)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validation mode: compare with JCR for 30 sample journals",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full mode: precompute IF for all journals",
    )
    parser.add_argument(
        "--issn",
        type=str,
        help="Calculate IF for a single ISSN (debug mode)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2023,
        help="Target year for IF calculation (default: 2023)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=2,
        choices=[2, 5],
        help="Citation window: 2 or 5 years (default: 2)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of journals to process (for testing)",
    )
    parser.add_argument(
        "--citable-only",
        action="store_true",
        default=True,
        help="Only count citable items (>20 refs) per JCR methodology (default: True)",
    )
    parser.add_argument(
        "--all-articles",
        action="store_true",
        help="Count all articles, not just citable items",
    )

    args = parser.parse_args()

    # Handle citable_only flag
    citable_only = not args.all_articles

    dsn = resolve_dsn(args.dsn)

    if args.issn:
        calculate_single_journal(dsn, args.issn, args.year)
    elif args.validate:
        validate_with_jcr(dsn, args.year, citable_only=citable_only)
    elif args.full:
        build_full_if_table(dsn, args.year, args.window, args.limit)
    else:
        parser.print_help()
        logger.info("\nExample usage:")
        logger.info("  python 07_build_if_table.py --validate          # Quick validation")
        logger.info("  python 07_build_if_table.py --issn 0028-0836    # Single journal")
        logger.info("  python 07_build_if_table.py --full              # Full precomputation")


if __name__ == "__main__":
    main()
