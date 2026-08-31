#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_system_deps.py
"""System (apt) dependency declarations for openalex-local.

openalex-local is the single source of truth for the OS-level packages its
snapshot pipeline needs. They are published under the
``scitex_dev.system_deps`` entry-point group so scitex-dev's aggregator
(``scitex-dev ecosystem system-deps``) federates them into ONE apt set at
container-build time, instead of hardcoding apt lists in container
definitions.

apt requires root, so installation happens at IMAGE-BUILD time (a container
``%post`` / Dockerfile), never at agent boot (agents run rootless
``--userns``). Declarations live here; install is build-time.

WHY awscli IS DECLARED HERE AND NOT LEFT TO THE PYTHON EXTRA
------------------------------------------------------------
``awscli`` is already a runtime dependency in ``pyproject.toml``, which
installs an ``aws`` console script into the VENV's ``bin/``. That is enough
for an interactive shell with the venv activated, and not enough for anything
else: the snapshot pipeline shells out to a bare ``aws``, which resolves
against the CALLER's ``PATH``, and a systemd unit or a cron job is handed a
minimal one that does not include the venv.

Measured on nas-03, 2026-08-16 -- ``openalex-update.service`` fired exactly on
schedule and died in under a second::

    2026-07-05 03:00:36,414 [INFO] Listing S3 directories...
    Error: [Errno 2] No such file or directory: 'aws'

while ``/home/ywatanabe/.venv-3.11/bin/aws`` existed the whole time. The
corpus then received no incremental update for six weeks, and nothing
reported it. Declaring the apt package puts ``aws`` on the default system
PATH, so every caller -- shell, systemd, cron, container -- finds it by the
same mechanism, instead of each one being patched to know where the venv is.

The Python dependency stays: it is what makes ``pip install openalex-local``
work on a machine we do not build the image for.
"""

from __future__ import annotations

import dataclasses

#: The declaring package name recorded on every SystemDepSpec.
PROVIDER = "openalex-local"


@dataclasses.dataclass(frozen=True)
class _Dep:
    """A keystone-independent apt declaration (so the CLI works even when an
    older scitex-dev without ``system_deps`` is installed)."""

    package: str
    purpose: str
    apt_repo: str | None = None


_APT_DEPS = [
    _Dep(
        "awscli",
        "aws s3 ls/sync against the public OpenAlex snapshot bucket; needed "
        "on the SYSTEM path because the update runs under systemd/cron, "
        "which do not see the venv's bin/",
    ),
]


def declarations() -> list[_Dep]:
    """Return openalex-local's raw apt declarations.

    Used by the leaf CLI so the listing renders without requiring the
    scitex-dev keystone to be importable.
    """
    return list(_APT_DEPS)


def provide():
    """Entry point for the ``scitex_dev.system_deps`` group.

    Maps this package's declarations onto scitex-dev's ``SystemDepSpec`` so the
    ecosystem aggregator can federate them. Imported lazily: only the
    aggregator (which runs with a keystone-capable scitex-dev) needs this call
    to succeed.
    """
    from scitex_dev.system_deps import SystemDepSpec

    return [
        SystemDepSpec(
            package=dep.package,
            purpose=dep.purpose,
            provider=PROVIDER,
            apt_repo=dep.apt_repo,
        )
        for dep in _APT_DEPS
    ]


# EOF
