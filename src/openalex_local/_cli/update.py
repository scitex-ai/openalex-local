#!/usr/bin/env python3
"""Update command for openalex-local CLI.

Thin Click wrapper over ``openalex_local.update`` (which forwards to the
project's differential-update logic). Kept in its own module to mirror
the ``status`` command extraction pattern and honour the line limit on
``cli.py``.
"""

import sys

import click


@click.command("update")
@click.option(
    "--db",
    "db_path",
    type=click.Path(),
    default=None,
    help="Database path override (else use auto-discovery).",
)
@click.option(
    "--since",
    default=None,
    help="Override start date (YYYY-MM-DD). Default: last recorded sync.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview only — no downloads or database writes.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip confirmation prompts (for cron/unattended runs).",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Minimal stdout (for cron).",
)
def update_cmd(db_path, since, dry_run, yes, quiet):
    """Incrementally update the local database from OpenAlex snapshots.

    Delta-syncs the S3 snapshot directories newer than the recorded
    last sync date and upserts them into the database.

    \b
    Example:
      $ openalex-local update
      $ openalex-local update --since 2026-03-01
      $ openalex-local update --dry-run
      $ openalex-local update --yes --quiet   # cron/unattended
    """
    from .. import update as _update

    if not dry_run and not yes:
        # REFUSE rather than prompt (ecosystem doctrine §2). This command's
        # primary caller is a systemd timer, and an interactive prompt in an
        # unattended context does not ask anybody anything -- it hangs, or it
        # reads EOF and takes the default. Refusing makes the missing flag
        # visible in the exit status instead of silently deciding for the
        # operator. Exit 2 is the conventional usage-error code.
        target = db_path or "the auto-discovered database"
        click.secho(
            f"Refusing to update {target} without --yes/-y.\n"
            "This rewrites the database in place. Re-run with --yes to "
            "proceed, or --dry-run to see what would change.",
            fg="red",
            err=True,
        )
        sys.exit(2)

    try:
        stats = _update(db_path=db_path, since=since, dry_run=dry_run)
    except Exception as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        sys.exit(1)

    upserted = stats.get("records_upserted", 0)
    last_sync = stats.get("last_sync_date", since or "unchanged")

    if stats.get("dry_run"):
        if not quiet:
            click.secho("[dry-run] no changes made.", fg="yellow")
        return

    if quiet:
        click.echo(f"{upserted} {last_sync}")
    else:
        click.secho(
            f"Update complete: {upserted:,} records upserted; "
            f"last_sync_date={last_sync}",
            fg="green",
        )


# EOF
