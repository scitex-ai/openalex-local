#!/usr/bin/env python3
"""Status command for openalex-local CLI."""

import sys

import click


@click.command("show-status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(as_json):
    """Show status and configuration.

    \b
    Example:
      $ openalex-local show-status
      $ openalex-local show-status --json
    """
    import json as json_module
    import os
    import urllib.request

    from .. import info
    from .._core.config import DEFAULT_PORT, corpus_target

    if as_json:
        try:
            status_data = info()
        except Exception as e:
            click.echo(
                json_module.dumps({"status": "error", "error": str(e)}, indent=2)
            )
            sys.exit(1)
        click.echo(json_module.dumps(status_data, indent=2))
        return

    click.secho("OpenAlex Local - Status", fg="cyan", bold=True)
    click.echo("=" * 50)
    click.echo()

    # Environment variables
    click.echo("Environment Variables:")
    click.echo()
    env_vars = [
        (
            "SCITEX_STORE_DSN",
            "Corpus DSN override (read by scitex_dev.store.host_store)",
        ),
        (
            "OPENALEX_LOCAL_API_URL",
            f"HTTP API URL (e.g., http://localhost:{DEFAULT_PORT})",
        ),
        ("OPENALEX_LOCAL_MODE", "Force mode: 'db', 'http', or 'auto'"),
        ("OPENALEX_LOCAL_HOST", "Host for relay server (default: 0.0.0.0)"),
        ("OPENALEX_LOCAL_PORT", f"Port for relay server (default: {DEFAULT_PORT})"),
    ]
    for var_name, description in env_vars:
        value = os.environ.get(var_name)
        if value:
            click.echo(f"  {var_name}={value}")
        else:
            click.echo(f"  {var_name} (not set)")
        click.echo(f"      | {description}")
        click.echo()

    # Where the corpus resolves to, and whether it answers. One line, not a
    # list of candidate locations: there is exactly one resolver now, so a
    # list of places that were searched would be reporting a search that no
    # longer happens.
    click.echo("Corpus:")
    db_found = False
    try:
        target = corpus_target()
        click.echo(f"  {target.describe()}")
        from .._core.db import corpus_available

        db_found = corpus_available()
        if db_found:
            click.secho("  [OK] reachable, works table present", fg="green")
        else:
            click.secho(
                "  [ ] unreachable, or reachable with no works table", fg="yellow"
            )
    except Exception as exc:
        click.secho(f"  [ ] cannot resolve: {exc}", fg="red")
    click.echo()

    # API health checks
    api_url = os.environ.get(
        "OPENALEX_LOCAL_API_URL", f"http://localhost:{DEFAULT_PORT}"
    )
    click.echo("API Health Checks:")
    health_url = f"{api_url}/health"
    click.echo(f"  $ curl {health_url}")
    api_healthy = False
    try:
        req = urllib.request.Request(health_url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json_module.loads(resp.read().decode())
                click.secho(f"    -> {data.get('status', 'ok')}", fg="green")
                api_healthy = True
            else:
                click.secho(f"    -> HTTP {resp.status}", fg="red")
    except Exception as e:
        click.secho(f"    -> unreachable ({type(e).__name__})", fg="red")
    click.echo()

    # Database info via /info endpoint
    if api_healthy:
        info_url = f"{api_url}/info"
        click.echo(f"  $ curl {info_url}")
        try:
            req = urllib.request.Request(info_url, method="GET")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json_module.loads(resp.read().decode())
                click.secho("    -> ok", fg="green")
                click.echo(f"Works: {data.get('total_works', 0):,}")
                click.echo(f"FTS Indexed: {data.get('fts_indexed', 0):,}")
                if data.get("sources_count"):
                    click.echo(
                        f"Sources/Journals: {data['sources_count']:,}"
                        " (impact factors available)"
                    )
        except Exception:
            click.secho("    -> timed out (server may need update)", fg="yellow")
            try:
                status_data = info()
                wc = status_data.get("work_count", status_data.get("works", 0))
                click.echo(f"Works: {wc:,}")
                click.echo(f"FTS Indexed: {status_data.get('fts_indexed', 0):,}")
            except Exception:
                pass
    elif db_found:
        try:
            status_data = info()
            wc = status_data.get("work_count", status_data.get("works", 0))
            click.echo(f"Works: {wc:,}")
            click.echo(f"FTS Indexed: {status_data.get('fts_indexed', 0):,}")
            if status_data.get("has_sources"):
                click.echo(
                    f"Sources/Journals: {status_data.get('sources_count', 0):,}"
                    " (impact factors available)"
                )
        except Exception as e:
            click.secho(f"Error: {e}", fg="red", err=True)
    else:
        click.secho("No database or API server found!", fg="red")
        click.echo()
        click.echo("Options:")
        click.echo("  1. Direct corpus access:")
        click.echo(
            "     export SCITEX_STORE_DSN=postgresql://user@host:55432/scitex"
        )
        click.echo()
        click.echo("  2. HTTP API (connect to relay server):")
        click.echo("     export OPENALEX_LOCAL_MODE=http")
