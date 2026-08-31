#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Timestamp: "2026-02-06 13:35:47 (ywatanabe)"
# File: examples/09_plot_if_vs_jcr.py


"""Plot Impact Factor Comparison: OpenAlex Calculated vs JCR.

Validates the JCR-style Impact Factor calculation against official JCR data.

Usage:
    python examples/09_plot_if_vs_jcr.py                    # Full JCR comparison
    python examples/09_plot_if_vs_jcr.py --sample 30        # Sample comparison
"""

import csv
import os
from pathlib import Path

import numpy as np
import scitex as stx
from scitex.stats.tests.correlation import test_pearson

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The JCR reference values. A CSV, and a CSV on purpose: the previous source
#: was a database file belonging to another package, read directly off that
#: package's disk layout. Reaching into a sibling project's storage makes this
#: example break whenever that project reorganises, for a table of about
#: 20,000 numbers that is perfectly well carried by a file.
#:
#: This is the same reference the IF build step validates against.
JCR_REFERENCE_CSV = Path(
    os.environ.get(
        "OPENALEX_LOCAL_JCR_CSV",
        "/home/ywatanabe/proj/crossref-local/examples/03_impact_factor/"
        "01_compare_jcr_out/all_combined.csv",
    )
)


def load_data():
    """Load both JCR and OpenAlex IF data."""
    # JCR reference values
    jcr_data = {}
    with open(JCR_REFERENCE_CSV) as handle:
        for row in csv.DictReader(handle):
            issn = (row.get("issn") or "").strip()
            raw = row.get("jcr_if")
            if not issn or not raw:
                continue
            try:
                jcr_data[issn] = {
                    "if": float(raw),
                    "journal": row.get("journal", ""),
                }
            except ValueError:
                continue

    # OpenAlex calculated IFs, from the corpus this host resolves to.
    from openalex_local._core.db import connection

    with connection() as db:
        rows = db.fetchall(
            "SELECT issn, impact_factor, journal_name "
            "FROM journal_impact_factors WHERE impact_factor IS NOT NULL"
        )
    oa_data = {
        row["issn"]: {"if": row["impact_factor"], "journal": row["journal_name"]}
        for row in rows
    }

    return jcr_data, oa_data


def plot_comparison(data, filename, title="", logger=None):
    """Create scatter plot using scitex.stats correlation test."""
    calc_if = np.array([d["calc_if"] for d in data])
    jcr_if = np.array([d["jcr_if"] for d in data])

    if len(calc_if) == 0:
        if logger:
            logger.warning("No valid data to plot")
        return None

    # Use scitex.stats.tests.correlation.test_pearson with plot=True
    result, fig = test_pearson(
        jcr_if,
        calc_if,
        var_x="JCR Impact Factor (2024)",
        var_y="SciTeX Impact Factor (OpenAlex)",
        plot=True,
        title=title or f"IF Comparison (n={len(calc_if):,})",
    )

    # Log results
    if logger:
        r = result.statistic["value"]
        p = result.p_value
        stars = result.stars
        logger.info(f"Pearson r = {r:.4f}, p = {p:.2e} {stars}")

    # Save using scitex.io
    stx.io.save(fig, filename, verbose=True)

    return result


@stx.session
def main(
    sample: int = 0,
    CONFIG=stx.session.INJECTED,
    plt=stx.session.INJECTED,
    logger=stx.session.INJECTED,
):
    """Plot IF comparison vs JCR.

    Args:
        sample: Limit to N sample journals (0 = all)
    """
    logger.info("Loading data...")
    jcr_data, oa_data = load_data()
    logger.info(f"JCR journals: {len(jcr_data):,}")
    logger.info(f"OpenAlex calculated: {len(oa_data):,}")

    # Match by ISSN
    matched = []
    for issn, jcr_info in jcr_data.items():
        if issn in oa_data:
            matched.append(
                {
                    "issn": issn,
                    "journal": jcr_info["journal"],
                    "jcr_if": jcr_info["if"],
                    "calc_if": oa_data[issn]["if"],
                    "ratio": (
                        oa_data[issn]["if"] / jcr_info["if"]
                        if jcr_info["if"] > 0
                        else None
                    ),
                }
            )

    if sample > 0:
        matched = matched[:sample]

    logger.info(f"Matched: {len(matched):,}")

    # Save JSON
    stx.io.save(matched, "comparison.json", verbose=True)

    # Plot all matched
    result_all = plot_comparison(
        matched,
        "scatter_all.png",
        "OpenAlex vs JCR Impact Factor",
        logger=logger,
    )

    # Plot by IF range
    low_if = [d for d in matched if d["jcr_if"] <= 5]
    mid_if = [d for d in matched if 5 < d["jcr_if"] <= 20]
    high_if = [d for d in matched if d["jcr_if"] > 20]

    if low_if:
        plot_comparison(
            low_if,
            "scatter_low_if.png",
            f"Low IF (<=5, n={len(low_if):,})",
            logger=logger,
        )
    if mid_if:
        plot_comparison(
            mid_if,
            "scatter_mid_if.png",
            f"Mid IF (5-20, n={len(mid_if):,})",
            logger=logger,
        )
    if high_if:
        plot_comparison(
            high_if,
            "scatter_high_if.png",
            f"High IF (>20, n={len(high_if):,})",
            logger=logger,
        )

    # Summary
    ratios = [d["ratio"] for d in matched if d["ratio"] is not None]
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Matched journals:  {len(matched):,}")
    if result_all:
        logger.info(f"Pearson r:         {result_all.statistic['value']:.4f}")
        logger.info(f"p-value:           {result_all.p_value:.2e}")
    logger.info(f"Ratio mean:        {np.mean(ratios):.2f}")
    logger.info(f"Ratio median:      {np.median(ratios):.2f}")

    return 0


if __name__ == "__main__":
    main()

# EOF
