#!/usr/bin/env python3
"""export-if command for openalex-local CLI.

Extracted from cli.py to keep the root module under the line limit
(mirrors the status.py extraction pattern).
"""

import json
import sys

import click


@click.command("export-if")
@click.option(
    "-o", "--output", default="scitex_if.csv", help="Output file (csv or json)"
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default=None,
    help="Output format (auto from extension)",
)
@click.option("--limit", type=int, default=0, help="Limit rows (0=all)")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be exported without writing the file.",
)
@click.option(
    "-y", "--yes", is_flag=True, help="Skip confirmation prompts (assume yes)."
)
def export_if(output, fmt, limit, dry_run, yes):
    """Export SciTeX Impact Factors (OpenAlex) to CSV or JSON.

    Exports precomputed journal impact factors from the database.
    Note: These are SciTeX IF values calculated from OpenAlex data,
    not JCR Impact Factors.

    \b
    Example:
      $ openalex-local export-if -o scitex_if.csv
      $ openalex-local export-if -o scitex_if.json --format json
      $ openalex-local export-if --limit 1000 --dry-run
    """
    if dry_run:
        click.secho(
            f"[dry-run] would export SciTeX IFs to {output} "
            f"(format={fmt or 'auto'}, limit={limit or 'all'})",
            fg="yellow",
        )
        return

    from .._core.db import get_db

    try:
        db = get_db()
    except Exception as exc:
        click.secho(f"Error: corpus unavailable: {exc}", fg="red")
        sys.exit(1)

    if not db.has_table("journal_impact_factors"):
        click.secho("Error: journal_impact_factors table not found", fg="red")
        click.echo("Run: make build-if-table")
        sys.exit(1)

    # Get data. LIMIT is bound rather than interpolated -- `limit` reaches here
    # from the command line, and a bound parameter cannot become SQL.
    query = (
        "SELECT issn, journal_name, year, impact_factor "
        "FROM journal_impact_factors "
        "WHERE impact_factor IS NOT NULL "
        "ORDER BY impact_factor DESC"
    )
    params: tuple = ()
    if limit > 0:
        query += " LIMIT %s"
        params = (limit,)

    rows = db.fetchall(query, params)

    # Determine format
    if fmt is None:
        fmt = "json" if output.endswith(".json") else "csv"

    columns = ("issn", "journal_name", "year", "impact_factor")

    if fmt == "json":
        data = [
            {
                "issn": r["issn"],
                "journal": r["journal_name"],
                "year": r["year"],
                "scitex_if": r["impact_factor"],
            }
            for r in rows
        ]
        with open(output, "w") as f:
            json.dump(data, f, indent=2)
    else:
        import csv

        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["issn", "journal", "year", "scitex_if"])
            writer.writerows([tuple(r[c] for c in columns) for r in rows])

    click.secho(f"Exported {len(rows):,} SciTeX IF values to {output}", fg="green")


# EOF
