"""
OpenAlex Local - Local OpenAlex database with 284M+ works and semantic search.

Example:
    >>> from openalex_local import search, get
    >>> results = search("machine learning neural networks")
    >>> work = get("W2741809807")  # OpenAlex ID
    >>> work = get("10.1038/nature12373")  # or DOI
"""

from __future__ import annotations

import importlib.metadata

__version__ = importlib.metadata.version("openalex-local")

from ._core import (
    SUPPORTED_FORMATS,
    SearchResult,
    Work,
    configure,
    count,
    enrich,
    enrich_ids,
    exists,
    get,
    get_many,
    get_mode,
    info,
    save,
    search,
    update,
)

# Jobs module (public functions only)
from . import jobs

# Async module
from . import aio

# Cache module
from . import cache

__all__ = [
    "__version__",
    # Core functions
    "search",
    "count",
    "get",
    "get_many",
    "exists",
    "info",
    # Maintenance
    "update",
    # Enrich functions
    "enrich",
    "enrich_ids",
    # Configuration
    "configure",
    "get_mode",
    # Models
    "Work",
    "SearchResult",
    # Export
    "save",
    "SUPPORTED_FORMATS",
    # Jobs
    "jobs",
    # Async
    "aio",
    # Cache
    "cache",
]
