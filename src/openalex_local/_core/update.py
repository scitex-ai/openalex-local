#!/usr/bin/env python3
"""Public API for incremental corpus updates."""

import importlib.util as _importlib_util
import os as _os
from pathlib import Path as _Path
from typing import Optional as _Optional

from .config import get_dsn as _get_dsn

__all__ = ["update"]

_REPO_ROOT = _Path(__file__).resolve().parents[3]
_SCRIPT_ENV_VAR = "OPENALEX_LOCAL_DIFFERENTIAL_UPDATE_SCRIPT"


def _load_differential_update():
    """Load the packaged updater or a caller's script override."""
    env_path = _os.environ.get(_SCRIPT_ENV_VAR)
    if not env_path:
        from ._differential_update import differential_update

        return differential_update
    script = _Path(env_path)
    if not script.exists():
        raise FileNotFoundError(
            f"Differential update script not found: {script}"
        )
    spec = _importlib_util.spec_from_file_location(
        "_openalex_local_differential_update", script
    )
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.differential_update


def _resolve_dsn(dsn: _Optional[str]) -> str:
    """The corpus to update: the caller's explicit choice, or this host's."""
    return dsn if dsn else _get_dsn()


def update(
    dsn: _Optional[str] = None,
    since: _Optional[str] = None,
    dry_run: bool = False,
    snapshot_dir: _Optional[str] = None,
) -> dict:
    """Incrementally update the local OpenAlex corpus.

    Downloads only the S3 snapshot directories newer than the recorded
    ``last_sync_date`` (or ``since`` when given) and upserts them into
    the corpus.

    Parameters
    ----------
    dsn : str, optional
        PostgreSQL connection string override. Defaults to the corpus
        ``scitex_dev.store.host_store`` resolves for this host, which
        ``SCITEX_STORE_DSN`` moves.
    since : str, optional
        Override start date (``YYYY-MM-DD``). Defaults to the recorded
        ``last_sync_date``.
    dry_run : bool
        Preview only — list what would be downloaded without writing.
    snapshot_dir : str, optional
        Snapshot works directory. Defaults to
        ``<repo>/data/snapshot/works`` in a checkout and the package runtime
        directory in a wheel installation.

    Returns
    -------
    dict
        Statistics from ``differential_update``: ``dates_processed``,
        ``records_upserted``, ``elapsed_seconds`` (and ``dry_run`` when
        applicable).
    """
    resolved_dsn = _resolve_dsn(dsn)
    if snapshot_dir:
        resolved_snapshot = _Path(snapshot_dir)
    elif (_REPO_ROOT / "scripts" / "database" / "10_differential_update.py").is_file():
        resolved_snapshot = _REPO_ROOT / "data" / "snapshot" / "works"
    else:
        from .paths import get_runtime_dir

        resolved_snapshot = get_runtime_dir() / "snapshot" / "works"

    differential_update = _load_differential_update()
    return differential_update(
        dsn=resolved_dsn,
        snapshot_dir=resolved_snapshot,
        since=since,
        dry_run=dry_run,
    )

# EOF
