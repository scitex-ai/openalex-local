#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/config.py
"""Configuration for openalex_local.

WHERE THE CORPUS LIVES IS NOT A SETTING THIS PACKAGE OWNS.
:func:`scitex_dev.store.host_store` resolves it — ``SCITEX_STORE_DSN`` if the
operator set one, otherwise this host's PostgreSQL — and that is the only
resolution path. The package-local ``OPENALEX_LOCAL_DB`` variable and the
four-entry ``DEFAULT_DB_PATHS`` search it drove are gone with it.

They are gone rather than deprecated because a second resolver is not a
convenience, it is a disagreement waiting to happen: the search list found
whichever half-built file happened to exist in the current working directory,
so the same command answered differently depending on where it was run, and
nothing in the output said which database had answered.
"""

import os as _os
from typing import Optional as _Optional

from scitex_dev.store import StoreTarget as _StoreTarget
from scitex_dev.store import host_store as _host_store

#: The package short name the store primitive keys runtime state on.
PKG = "openalex_local"

#: The corpus store's name within this package. A package may hold several
#: (see :mod:`._state` for the metadata one); naming them keeps two record
#: kinds from colliding in one table namespace.
CORPUS_STORE = "corpus"

DEFAULT_PORT = 31292
DEFAULT_HOST = "0.0.0.0"

_POSTGRES_SCHEMES = ("postgresql://", "postgres://")


def corpus_target() -> _StoreTarget:
    """The resolved pointer to this host's corpus.

    Returns a :class:`~scitex_dev.store.StoreTarget` rather than a string so
    the answer can be logged and compared without re-deriving it — and so it
    cannot be handed to a filesystem API by accident.
    """
    return _host_store(pkg=PKG, name=CORPUS_STORE)


def get_dsn() -> str:
    """The corpus connection string for this host."""
    return corpus_target().dsn


class Config:
    """Configuration container."""

    _dsn: _Optional[str] = None
    _api_url: _Optional[str] = None
    _mode: str = "auto"  # "auto", "db", or "http"

    @classmethod
    def get_dsn(cls) -> str:
        if cls._dsn is None:
            cls._dsn = get_dsn()
        return cls._dsn

    @classmethod
    def set_dsn(cls, dsn: str) -> None:
        """Point this process at an explicit corpus, and switch to db mode.

        Refuses anything that is not a PostgreSQL DSN. A path used to be
        accepted here and meant a file; accepting one now would silently
        select a database that does not exist rather than saying so.
        """
        if not dsn or not str(dsn).strip():
            raise ValueError(
                "empty corpus DSN. Pass a PostgreSQL connection string "
                "(postgresql://user@host:55432/scitex), or leave it unset "
                "and let SCITEX_STORE_DSN / this host's store decide."
            )
        value = str(dsn).strip()
        if not value.lower().startswith(_POSTGRES_SCHEMES):
            raise ValueError(
                f"{value!r} is not a PostgreSQL DSN. It must start with "
                "'postgresql://' or 'postgres://'. The corpus lives in "
                "PostgreSQL; a filesystem path names no database this "
                "package can open."
            )
        cls._dsn = value
        cls._mode = "db"

    @classmethod
    def get_api_url(cls) -> str:
        if cls._api_url:
            return cls._api_url
        return _os.environ.get(
            "OPENALEX_LOCAL_API_URL", f"http://localhost:{DEFAULT_PORT}"
        )

    @classmethod
    def set_api_url(cls, url: str) -> None:
        cls._api_url = url.rstrip("/")
        cls._mode = "http"

    @classmethod
    def set_mode(cls, mode: str) -> None:
        """Set mode explicitly: 'db', 'http', or 'auto'."""
        if mode not in ("auto", "db", "http"):
            raise ValueError(f"Invalid mode: {mode}. Use 'auto', 'db', or 'http'")
        cls._mode = mode

    @classmethod
    def get_mode(cls) -> str:
        """
        Get current mode.

        Returns:
            "db" if using direct database access
            "http" if using HTTP API
        """
        if cls._mode == "auto":
            # Check environment variable for explicit mode
            env_mode = _os.environ.get("OPENALEX_LOCAL_MODE", "").lower()
            if env_mode in ("http", "remote", "api"):
                return "http"
            if env_mode in ("db", "local"):
                return "db"

            # Check if API URL is set explicitly
            if cls._api_url or _os.environ.get("OPENALEX_LOCAL_API_URL"):
                return "http"

            # Check whether the corpus is actually reachable and populated.
            from .db import corpus_available

            return "db" if corpus_available() else "http"

        return cls._mode

    @classmethod
    def reset(cls) -> None:
        cls._dsn = None
        cls._api_url = None
        cls._mode = "auto"


# EOF
