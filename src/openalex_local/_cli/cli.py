#!/usr/bin/env python3
"""CLI for openalex_local."""

import json
import sys

import click

from .. import __version__


class AliasedGroup(click.Group):
    """Click group with command aliases."""

    ALIASES = {
        "s": "search",
        "doi": "search-by-doi",
        "st": "show-status",
        "status": "show-status",
    }

    def get_command(self, ctx, cmd_name):
        # Check for alias
        cmd_name = self.ALIASES.get(cmd_name, cmd_name)
        return super().get_command(ctx, cmd_name)

    def resolve_command(self, ctx, args):
        # Resolve alias before normal command resolution
        _, cmd_name, args = super().resolve_command(ctx, args)
        return _, cmd_name, args


def _print_recursive_help(ctx, param, value):
    """Callback for --help-recursive flag."""
    if not value or ctx.resilient_parsing:
        return

    def _print_command_help(cmd, prefix: str, parent_ctx):
        """Recursively print help for a command and its subcommands."""
        click.secho(f"\n━━━ {prefix} ━━━", fg="cyan", bold=True)
        sub_ctx = click.Context(cmd, info_name=prefix.split()[-1], parent=parent_ctx)
        click.echo(cmd.get_help(sub_ctx))

        if isinstance(cmd, click.Group):
            for sub_name, sub_cmd in sorted(cmd.commands.items()):
                _print_command_help(sub_cmd, f"{prefix} {sub_name}", sub_ctx)

    # Print main help
    click.secho("━━━ openalex-local ━━━", fg="cyan", bold=True)
    click.echo(ctx.get_help())

    # Print all subcommands recursively
    for name, cmd in sorted(cli.commands.items()):
        _print_command_help(cmd, f"openalex-local {name}", ctx)

    ctx.exit(0)


@click.group(cls=AliasedGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.help_option("-h", "--help")
@click.version_option(__version__, "-V", "--version")
@click.option("--http", is_flag=True, help="Use HTTP API instead of direct database")
@click.option("--api-url", help="API URL for http mode (default: auto-detect)")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON output (where supported).",
)
@click.option(
    "--help-recursive",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_print_recursive_help,
    help="Show help for all commands recursively.",
)
@click.pass_context
def cli(ctx, http, api_url, as_json):
    """
    Local OpenAlex database with 284M+ works and full-text search.

    \b
    Supports both direct database access (db mode) and HTTP API (http mode).

    \b
    DB mode (default if database found):
      openalex-local search "machine learning"

    \b
    HTTP mode (connect to API server):
      openalex-local --http search "machine learning"

    \b
    Configuration precedence (highest -> lowest):
      1. CLI flags / function kwargs
      2. ./config.yaml (project-local)
      3. $OPENALEX_LOCAL_CONFIG (env var pointing to a YAML file)
      4. ~/.scitex/openalex-local/config.yaml (user-level)
      5. built-in defaults
    """
    ctx.ensure_object(dict)
    ctx.obj["as_json"] = as_json

    if http or api_url:
        from .._core.api import configure_http

        configure_http(api_url or "http://localhost:31292")


@cli.command("search")
@click.argument("query")
@click.option("-n", "--number", default=10, help="Number of results")
@click.option("-o", "--offset", default=0, help="Skip first N results")
@click.option("-a", "--abstracts", is_flag=True, help="Show abstracts")
@click.option("-A", "--authors", is_flag=True, help="Show authors")
@click.option("--concepts", is_flag=True, help="Show concepts/topics")
@click.option(
    "-if", "--impact-factor", "with_if", is_flag=True, help="Show journal impact factor"
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--save", "save_path", type=click.Path(), help="Save results to file")
@click.option(
    "--format",
    "save_format",
    type=click.Choice(["text", "json", "bibtex"]),
    default="json",
    help="Output format for --save (default: json)",
)
def search_cmd(
    query,
    number,
    offset,
    abstracts,
    authors,
    concepts,
    with_if,
    as_json,
    save_path,
    save_format,
):
    """Search for works by title, abstract, or authors.

    \b
    Example:
      $ openalex-local search "machine learning" -n 5
      $ openalex-local search "CRISPR" --json
      $ openalex-local search "deep learning" --abstracts --authors
    """
    from .. import search
    from .._core.db import get_db

    try:
        results = search(query, limit=number, offset=offset)
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        sys.exit(1)
    except ConnectionError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        click.secho(
            "\nHint: Make sure the relay server is running:", fg="yellow", err=True
        )
        click.secho("  1. On the db-host: openalex-local relay", fg="yellow", err=True)
        click.secho(
            "  2. SSH tunnel: ssh -L 31292:127.0.0.1:31292 <db-host>",
            fg="yellow",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        sys.exit(1)

    # Enrich with impact factor data if requested
    if_cache = {}
    if with_if:
        try:
            db = get_db()
            if db.has_sources_table():
                for work in results.works:
                    if work.issn and work.issn not in if_cache:
                        metrics = db.get_source_metrics(work.issn)
                        if_cache[work.issn] = metrics
                    if work.issn and if_cache.get(work.issn):
                        metrics = if_cache[work.issn]
                        work.scitex_if = metrics.get("scitex_if")
                        work.source_h_index = metrics.get("source_h_index")
                        work.source_cited_by_count = metrics.get(
                            "source_cited_by_count"
                        )
            else:
                click.secho(
                    "Warning: sources table not found. Run: python scripts/database/04_build_sources_table.py",
                    fg="yellow",
                    err=True,
                )
        except Exception as e:
            click.secho(
                f"Warning: Could not fetch impact factors: {e}", fg="yellow", err=True
            )

    # Save to file if requested
    if save_path:
        from .._core.export import save as _save

        try:
            saved = _save(
                results, save_path, format=save_format, include_abstract=abstracts
            )
            click.secho(
                f"Saved {len(results)} results to {saved}", fg="green", err=True
            )
        except Exception as e:
            click.secho(f"Error saving: {e}", fg="red", err=True)
            sys.exit(1)

    if as_json:
        output = {
            "query": query,
            "total": results.total,
            "elapsed_ms": results.elapsed_ms,
            "works": [w.to_dict() for w in results.works],
        }
        click.echo(json.dumps(output, indent=2))
        return

    click.secho(
        f"Found {results.total:,} matches in {results.elapsed_ms:.1f}ms\n",
        fg="green",
    )

    for i, work in enumerate(results.works, 1):
        click.secho(f"{i}. {work.title} ({work.year})", fg="cyan", bold=True)
        click.echo(f"   DOI: {work.doi or 'N/A'}")
        journal_info = work.source or "N/A"
        if with_if and work.scitex_if is not None:
            journal_info += f" (SciTeX IF: {work.scitex_if:.1f})"
        click.echo(f"   Journal: {journal_info}")
        if with_if:
            click.echo(
                f"   Citations: {work.cited_by_count or 0} (journal total: {work.source_cited_by_count or 'N/A'})"
            )

        if authors and work.authors:
            author_str = ", ".join(work.authors[:5])
            if len(work.authors) > 5:
                author_str += f" (+{len(work.authors) - 5} more)"
            click.echo(f"   Authors: {author_str}")

        if abstracts and work.abstract:
            abstract = work.abstract[:300]
            if len(work.abstract) > 300:
                abstract += "..."
            click.echo(f"   Abstract: {abstract}")

        if concepts and work.concepts:
            concept_names = [c.get("name", "") for c in work.concepts[:5]]
            click.echo(f"   Concepts: {', '.join(concept_names)}")

        click.echo()


# search-by-doi command (extracted to separate module for line limit)
from .search_by_doi import search_by_doi_cmd

cli.add_command(search_by_doi_cmd)


# Status command (extracted to separate module for line limit)
from .status import status_cmd

cli.add_command(status_cmd)


# Database group (extracted to separate module for line limit).
#
# `update` used to sit at top level, which the CLI audit rejects under §1: a
# bare transitive verb with no object. It updates the local DATABASE, so the
# object becomes the group — `openalex-local db update`. Nesting also gives the
# forthcoming build/verify verbs somewhere coherent to live.
#
# The old spelling is a PUBLISHED CONTRACT: `openalex-update.service` on nas-03
# invokes `openalex-local update --yes --quiet`. So this is a migration, not a
# rename — the alias forwards and warns, and only disappears at the version
# named below.
from .db_group import db_group

cli.add_command(db_group)

try:
    from scitex_dev.ecosystem import deprecated_alias as _deprecated_alias
except ImportError:  # pragma: no cover - keystone absent in a bare install
    pass
else:
    _deprecated_alias(
        cli,
        "update",
        target=db_group.commands["update"],
        remove_in="0.9",
        target_name="db update",
    )


# Register MCP subcommand group
from .mcp import mcp

cli.add_command(mcp)

# Register cache subcommand group
from .cli_cache import cache_group

cli.add_command(cache_group)


@cli.command("relay")
@click.option("--host", default=None, envvar="OPENALEX_LOCAL_HOST", help="Host to bind")
@click.option(
    "--port",
    default=None,
    type=int,
    envvar="OPENALEX_LOCAL_PORT",
    help="Port to listen on (default: 31292)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Kill existing process using the port if any",
)
def relay(host: str, port: int, force: bool):
    """Run HTTP relay server for remote database access.

    \b
    This runs a FastAPI server that provides proper full-text search
    using the full-text index across all 284M+ papers.

    \b
    Example:
      openalex-local relay                  # Run on 0.0.0.0:31292
      openalex-local relay --port 8080      # Custom port
      openalex-local relay --force          # Kill existing process if port in use

    \b
    Then connect with http mode:
      openalex-local --http search "CRISPR"
      curl "http://localhost:31292/works?q=CRISPR&limit=10"
    """
    try:
        from .._server import DEFAULT_HOST, DEFAULT_PORT, run_server
    except ImportError:
        click.echo(
            "API server requires fastapi and uvicorn. Install with:\n"
            "  pip install fastapi uvicorn",
            err=True,
        )
        sys.exit(1)

    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT

    # Handle force flag
    if force:
        from .utils import kill_process_on_port

        kill_process_on_port(port)

    click.echo(f"Starting OpenAlex Local relay server on {host}:{port}")
    click.echo(f"Search endpoint: http://{host}:{port}/works?q=<query>")
    click.echo(f"Docs: http://{host}:{port}/docs")
    run_server(host=host, port=port)


# export-if command (extracted to separate module for line limit)
from .export_if import export_if

cli.add_command(export_if)


# Register docs and skills subcommands (from scitex-dev)
try:
    from scitex_dev.cli import docs_click_group, skills_click_group

    cli.add_command(docs_click_group(package="openalex-local"))
    cli.add_command(skills_click_group(package="openalex-local"))
except ImportError:
    pass


# Wire canonical install-shell-completion + print-shell-completion (§1a)
try:
    from scitex_dev._cli._completion import attach_shell_completion

    attach_shell_completion(cli, prog_name="openalex-local")
except ImportError:
    pass


@cli.command("list-python-apis")
@click.option(
    "-v", "--verbose", count=True, help="Verbosity: -v sig, -vv +doc, -vvv full"
)
@click.option("-d", "--max-depth", type=int, default=5, help="Max recursion depth")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_python_apis(verbose, max_depth, as_json):
    """List Python APIs (alias for: scitex introspect api openalex_local).

    \b
    Example:
      $ openalex-local list-python-apis
      $ openalex-local list-python-apis -v
      $ openalex-local list-python-apis --json
    """
    try:
        from scitex.cli.introspect import api

        ctx = click.Context(api)
        ctx.invoke(
            api,
            dotted_path="openalex_local",
            verbose=verbose,
            max_depth=max_depth,
            as_json=as_json,
        )
    except ImportError:
        # Fallback if scitex not installed
        click.echo("Install scitex for full API introspection:")
        click.echo("  pip install scitex")
        click.echo()
        click.echo("Or use: scitex introspect api openalex_local")


def main():
    """Entry point for CLI."""
    cli()


# audit §4 — inject version into root --help. `main` is a thin
# wrapper; the click Group is `cli`.
try:
    from importlib.metadata import version as _v

    cli.help = (
        f"openalex-local (v{_v('openalex-local')}) — " + (cli.help or "").lstrip()
    )
except Exception:
    pass


if __name__ == "__main__":
    main()
