#!/usr/bin/env python3
"""Incremental corpus update for openalex_local.

Thin wrapper around the project's differential-update logic
(``scripts/database/10_differential_update.py``). Delta-syncs the OpenAlex S3
snapshot directories newer than the recorded ``last_sync_date`` and upserts
them into the corpus.

The heavy lifting is NOT reimplemented here — this module only resolves the
target and forwards to ``differential_update`` so the CLI (``openalex-local db
update``) and the Python API (``openalex_local.update``) share one code path.

WHERE IT WRITES is resolved by ``scitex_dev.store.host_store``. There is no
first-run fallback to a repo-local file any more: that fallback existed to
create a database where none was found, and it is exactly the behaviour that
let an update quietly build a second, private corpus in whatever directory the
timer happened to start in. If the store is unreachable this now fails and
says so.
"""

import importlib.util as _importlib_util
import os as _os
from pathlib import Path as _Path
from typing import Optional as _Optional

from .config import get_dsn as _get_dsn

__all__ = ["update"]

# Repo root: <repo>/src/openalex_local/_core/update.py -> parents[3].
_REPO_ROOT = _Path(__file__).resolve().parents[3]
_DEFAULT_DIFFERENTIAL_UPDATE_SCRIPT = (
    _REPO_ROOT / "scripts" / "database" / "10_differential_update.py"
)
# Env override — lets callers (and tests) point at an alternate script
# that exposes the same ``differential_update`` entry point.
_SCRIPT_ENV_VAR = "OPENALEX_LOCAL_DIFFERENTIAL_UPDATE_SCRIPT"


def _differential_update_script() -> _Path:
    """Resolve the differential-update script path (env override first)."""
    env_path = _os.environ.get(_SCRIPT_ENV_VAR)
    if env_path:
        return _Path(env_path)
    return _DEFAULT_DIFFERENTIAL_UPDATE_SCRIPT


def _load_differential_update():
    """Load ``differential_update`` from the database script.

    The sync logic lives under ``scripts/`` (outside the importable
    package), so it is loaded by file path rather than reimplemented.
    """
    script = _differential_update_script()
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
        ``<repo>/data/snapshot/works``.

    Returns
    -------
    dict
        Statistics from ``differential_update``: ``dates_processed``,
        ``records_upserted``, ``elapsed_seconds`` (and ``dry_run`` when
        applicable).
    """
    resolved_dsn = _resolve_dsn(dsn)
    resolved_snapshot = (
        _Path(snapshot_dir)
        if snapshot_dir
        else _REPO_ROOT / "data" / "snapshot" / "works"
    )

    differential_update = _load_differential_update()
    return differential_update(
        dsn=resolved_dsn,
        snapshot_dir=resolved_snapshot,
        since=since,
        dry_run=dry_run,
    )

# EOF
