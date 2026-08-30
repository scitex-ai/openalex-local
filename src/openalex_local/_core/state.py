#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/state.py
"""Build metadata, kept in the fleet's store primitive.

This is the half of the old database that IS runtime state: a handful of
key/value records — ``total_works``, ``fts_total_indexed``, when each was
last rebuilt — written by the build scripts and read by ``openalex-local
show-status``. It used to be a ``_metadata`` table inside the corpus, which
meant a stat about the corpus could only be read by opening the corpus, and
a half-built corpus therefore had no readable stats at all.

So it moves to :class:`scitex_dev.store.Store`, which is what that primitive
is for. Three properties come with it and none of them are reimplemented
here:

* **Optimistic locking.** Two build steps finishing at once cannot silently
  lose one another's counter.
* **Nothing is deleted.** The store has no delete verb; a superseded value
  stays readable in the oplog, so "when did this counter last change, and to
  what?" is answerable after the fact.
* **One resolver.** The target comes from
  :func:`scitex_dev.store.host_store`, the same call :mod:`._core.db` uses,
  so the metadata and the corpus cannot end up on different hosts.

The corpus itself deliberately does NOT live in a ``Store`` — see the module
docstring of :mod:`._core.db` for why 284M snapshot rows are the wrong shape
for an oplog.
"""

from __future__ import annotations

import socket as _socket
from typing import Optional

from scitex_dev.store import (
    ANY_REVISION,
    FieldKind,
    FieldPolicy,
    FieldRole,
    MergeRule,
    Schema,
    Store,
    WriterPolicy,
    host_store,
)

from .config import PKG

__all__ = [
    "METADATA_SCHEMA",
    "METADATA_STORE",
    "get_metadata",
    "metadata_store",
    "set_metadata",
]

#: The store's name within this package, alongside ``corpus``.
METADATA_STORE = "metadata"

#: Fully declared, because ``Store.put`` raises on a field with no policy
#: rather than inventing one. There is no default merge rule for the same
#: reason there is no default database: a wrong one loses data quietly.
METADATA_SCHEMA = Schema.build(
    "openalex_metadata",
    {
        "key": FieldPolicy(
            kind=FieldKind.TEXT,
            role=FieldRole.IDENTITY,
            required=True,
            merge=MergeRule.IMMUTABLE,
            indexed=False,
        ),
        "value": FieldPolicy(
            kind=FieldKind.TEXT,
            role=FieldRole.DATA,
            required=True,
            merge=MergeRule.LAST_WRITER_WINS,
            indexed=False,
        ),
    },
)


def metadata_store(*, node: Optional[str] = None) -> Store:
    """Open the metadata store for this host.

    ``node`` names the WRITER — it numbers the oplog and breaks clock ties.
    It defaults to the hostname, which is right for a build script; an agent
    sharing a host with others should pass its own name so the two are
    distinguishable in the log.

    ``MULTI_WRITER`` because the build steps run as different processes and
    each owns a different counter; requiring a single writer would make step
    03 unable to record its own progress after step 02 created the record.
    """
    return Store(
        host_store(pkg=PKG, name=METADATA_STORE),
        METADATA_SCHEMA,
        node=node or _socket.gethostname(),
        writer_policy=WriterPolicy.MULTI_WRITER,
    )


def set_metadata(key: str, value: str, *, node: Optional[str] = None) -> None:
    """Record one build statistic.

    ``ANY_REVISION`` is correct here and would not be correct for a card:
    these counters are recomputed from the corpus by whichever step just
    finished, so the newest measurement always wins and there is no earlier
    value a writer could be clobbering unknowingly.
    """
    with metadata_store(node=node) as store:
        store.put({"key": key, "value": str(value)}, expected_revision=ANY_REVISION)


def get_metadata(key: str, *, node: Optional[str] = None) -> Optional[str]:
    """Read one build statistic, or None when it was never recorded."""
    with metadata_store(node=node) as store:
        row = store.get({"key": key})
        return None if row is None else row.values.get("value")

# EOF
