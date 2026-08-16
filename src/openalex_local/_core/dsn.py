#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/dsn.py
"""Resolve `OPENALEX_LOCAL_DB` into a declared, typed target.

The corpus is moving off a bind-mounted SQLite file and onto Postgres, so the
setting that used to mean "a path" has to mean "a place" without breaking the
callers that still pass a path. One field carries all three spellings:

    /data/openalex.db                            -> sqlite   (unchanged)
    sqlite:///data/openalex.db                   -> sqlite   (explicit)
    postgresql://user@host:55501/openalex        -> postgres

ONE FIELD, NOT TWO. A separate `backend=` setting alongside a `path=` setting
is a state that can disagree with itself, and someone eventually reads the one
that is wrong. The DSN already carries the backend; parsing it is cheaper than
keeping two facts in sync.

The return is always the same dataclass with the same fields, validated at
construction, per the constitution's fixed-shape rule: a caller must never have
to guess which attribute exists on this particular call.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

__all__ = ["Backend", "DsnTarget", "UnsupportedDsn", "parse_dsn"]

#: Schemes we serve, and the backend each selects.
_SQLITE_SCHEMES = ("sqlite://", "file:")
_POSTGRES_SCHEMES = ("postgresql://", "postgres://")


class Backend:
    """The storage engines this package supports.

    Deliberately a closed set of two. A third value would be a promise no
    implementation stands behind.
    """

    SQLITE = "sqlite"
    POSTGRES = "postgres"

    ALL = (SQLITE, POSTGRES)


class UnsupportedDsn(ValueError):
    """The DSN named a scheme this package has no backend for."""


@dataclasses.dataclass(frozen=True)
class DsnTarget:
    """Where the corpus lives, in a shape every caller can rely on.

    Fields
    ------
    backend
        One of ``Backend.ALL``. Never None: a target that cannot name its
        backend is not a target.
    raw
        The DSN exactly as it was supplied, for error messages. Never
        reconstructed from the parsed parts — a message that quotes a
        normalised string sends the reader looking for text they never wrote.
    path
        The filesystem path, for ``sqlite`` only. None for ``postgres``.
    url
        The connection URL, for ``postgres`` only. None for ``sqlite``.

    The two optional fields are mutually exclusive by construction, so
    ``target.path`` being None is never ambiguous — it means postgres, and
    ``backend`` says so directly.
    """

    backend: str
    raw: str
    path: Optional[Path] = None
    url: Optional[str] = None

    def __post_init__(self) -> None:
        # Validate where the value is BUILT, not three layers downstream.
        if self.backend not in Backend.ALL:
            raise ValueError(
                f"DsnTarget.backend must be one of {Backend.ALL}; got {self.backend!r}"
            )
        if self.backend == Backend.SQLITE:
            if self.path is None:
                raise ValueError(f"sqlite target has no path (raw={self.raw!r})")
            if self.url is not None:
                raise ValueError(
                    f"sqlite target must not carry a url (raw={self.raw!r})"
                )
        else:
            if self.url is None:
                raise ValueError(f"postgres target has no url (raw={self.raw!r})")
            if self.path is not None:
                raise ValueError(
                    f"postgres target must not carry a path (raw={self.raw!r})"
                )

    @property
    def is_sqlite(self) -> bool:
        return self.backend == Backend.SQLITE

    @property
    def is_postgres(self) -> bool:
        return self.backend == Backend.POSTGRES


def parse_dsn(value: str) -> DsnTarget:
    """Parse one DSN or path into a :class:`DsnTarget`.

    A bare path is sqlite. That is the back-compatible reading and it is also
    the honest one: every existing caller passes a path and means a file.

    Raises
    ------
    ValueError
        If ``value`` is empty. An empty setting is not "use the default" —
        the caller asked for something and supplied nothing, which is a
        mistake worth surfacing rather than papering over.
    UnsupportedDsn
        If a scheme is present and is not one we serve. Naming the schemes we
        do support is the actionable half of the message.
    """
    if value is None or not str(value).strip():
        raise ValueError(
            "empty database DSN. Set OPENALEX_LOCAL_DB to a path "
            "(/data/openalex.db) or a URL "
            "(postgresql://user@host:55501/openalex), or unset it entirely to "
            "fall back to the default search paths."
        )

    raw = str(value).strip()
    lowered = raw.lower()

    if lowered.startswith(_POSTGRES_SCHEMES):
        return DsnTarget(backend=Backend.POSTGRES, raw=raw, url=raw)

    if lowered.startswith("sqlite://"):
        # sqlite:///abs/path -> /abs/path ; sqlite://rel/path -> rel/path
        remainder = raw[len("sqlite://") :]
        return DsnTarget(backend=Backend.SQLITE, raw=raw, path=Path(remainder))

    if lowered.startswith("file:"):
        return DsnTarget(
            backend=Backend.SQLITE, raw=raw, path=Path(raw[len("file:") :])
        )

    if "://" in raw:
        scheme = raw.split("://", 1)[0]
        raise UnsupportedDsn(
            f"unsupported DSN scheme {scheme!r} in {raw!r}. This package "
            f"serves sqlite and postgresql only. Use a bare path or "
            f"sqlite:///path for a file, or postgresql://... for a server."
        )

    return DsnTarget(backend=Backend.SQLITE, raw=raw, path=Path(raw))


# EOF
