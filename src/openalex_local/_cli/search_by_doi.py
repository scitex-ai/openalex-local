#!/usr/bin/env python3
"""search-by-doi command for openalex-local CLI.

Extracted from cli.py to keep the root module under the line limit
(mirrors the status.py extraction pattern).
"""

import json
import sys

import click


@click.command("search-by-doi")
@click.argument("doi")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--citation", is_flag=True, help="Output as APA citation")
@click.option("--bibtex", is_flag=True, help="Output as BibTeX entry")
@click.option("--save", "save_path", type=click.Path(), help="Save result to file")
@click.option(
    "--format",
    "save_format",
    type=click.Choice(["text", "json", "bibtex"]),
    default="json",
    help="Output format for --save (default: json)",
)
def search_by_doi_cmd(doi, as_json, citation, bibtex, save_path, save_format):
    """Search for a work by DOI.

    \b
    Example:
      $ openalex-local search-by-doi 10.1038/nature12373
      $ openalex-local search-by-doi 10.1038/nature12373 --json
      $ openalex-local search-by-doi 10.1038/nature12373 --bibtex
    """
    from .. import get

    try:
        work = get(doi)
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        sys.exit(1)

    if work is None:
        click.secho(f"Not found: {doi}", fg="red", err=True)
        sys.exit(1)

    # Save to file if requested
    if save_path:
        from .._core.export import save as _save

        try:
            saved = _save(work, save_path, format=save_format)
            click.secho(f"Saved to {saved}", fg="green", err=True)
        except Exception as e:
            click.secho(f"Error saving: {e}", fg="red", err=True)
            sys.exit(1)

    if citation:
        click.echo(work.citation("apa"))
        return

    if bibtex:
        click.echo(work.citation("bibtex"))
        return

    if as_json:
        click.echo(json.dumps(work.to_dict(), indent=2))
        return

    click.secho(work.title, fg="cyan", bold=True)
    click.echo(f"DOI: {work.doi}")
    click.echo(f"OpenAlex ID: {work.openalex_id}")
    click.echo(f"Year: {work.year or 'N/A'}")
    click.echo(f"Journal: {work.source or 'N/A'}")
    click.echo(f"Type: {work.type or 'N/A'}")
    click.echo(f"Citations: {work.cited_by_count or 0}")

    if work.authors:
        click.echo(f"Authors: {', '.join(work.authors)}")

    if work.abstract:
        click.echo(f"\nAbstract:\n{work.abstract}")

    if work.is_oa and work.oa_url:
        click.echo(f"\nOpen Access: {work.oa_url}")


# EOF
